import asyncio
import os
import pickle
import time
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.async_api import async_playwright
from rich.progress import Progress

def is_valid_url(url: str) -> bool:
    # Check if the provided string is a valid URL
    parsed = urlparse(url)
    return bool(parsed.scheme and parsed.netloc)

def normalize_url(url: str) -> str:
    # Normalize a URL by removing its fragment to avoid duplicate scraping
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))

def same_site(url1, url2):
    # Ignores scheme differences, e.g. https vs http, 
    # but checks domain and optional port
    return urlparse(url1).netloc == urlparse(url2).netloc

async def scrape_page(page, url):
    # Scrape the text content from a given URL.
    await page.goto(url)
    await page.wait_for_load_state('networkidle')
    # Extract text from the entire body; adjust selector if needed for specific content
    content = await page.inner_text('body')
    return content

async def main():
    # Prompt user for URL and validate
    while True:
        root_url = input("Please enter the URL to scrape: ")
        if is_valid_url(root_url):
            break
        else:
            print("Invalid URL. Please try again.\n")

    # Normalize the root URL
    starting_url = normalize_url(root_url)

    # Initialize data structures and load state if available
    if os.path.exists('state.pkl'):
        with open('state.pkl', 'rb') as f:
            state = pickle.load(f)
            queue = state['queue']
            visited = state['visited']
            in_queue = state['in_queue']
        print("Resuming from previous state...")
    else:
        queue = deque([starting_url])  # URLs to scrape
        visited = set()            # Tracks URLs already scraped
        in_queue = set([starting_url]) # Tracks URLs in the queue

    # Initialize backup variables
    last_backup = time.time()
    backup_interval = 120  # 2 minutes in seconds
    pages_processed = 0

    # Open the output file in append mode
    with open("llm.txt", "a", encoding="utf-8") as content_file, \
         open("links_visited.txt", "a", encoding="utf-8") as links_visited_file:

        # Set up progress bar with initial total based on queue
        with Progress() as progress:
            task = progress.add_task("Scraping", total=len(visited) + len(queue))
            
            # Launch Playwright browser
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                # Process the queue
                while queue:
                    current_url = queue.popleft()
                    in_queue.remove(current_url)

                    try:
                        # Scrape the page content
                        content = await scrape_page(page, current_url)
                        content_file.write(f"URL: {current_url}\n\n{content}\n\n---\n")
                        visited.add(current_url)

                        # Log this visited URL to links_visited.txt
                        links_visited_file.write(current_url + "\n")

                        # Find all links on the page
                        links = await page.query_selector_all('a, area')
                        for link in links:
                            href = await link.get_attribute('href')
                            if href:
                                # Resolve relative URLs
                                full_url = urljoin(current_url, href)
                                normalized_url = normalize_url(full_url)

                                # Only enqueue if it's the same domain and not visited/in_queue
                                if (same_site(starting_url, normalized_url)
                                    and normalized_url not in visited
                                    and normalized_url not in in_queue):
                                    queue.append(normalized_url)
                                    in_queue.add(normalized_url)

                    except Exception as e:
                        print(f"Error at {current_url}: {e}")

                    # Update progress: total is visited + queued, completed is visited
                    progress.update(task, total=len(visited) + len(queue), completed=len(visited))

                    # Update backup variables
                    pages_processed += 1
                    current_time = time.time()

                    # Save state periodically
                    if (current_time - last_backup >= backup_interval) or (pages_processed % 100 == 0):
                        with open('state.pkl', 'wb') as f:
                            pickle.dump({'queue': queue, 'visited': visited, 'in_queue': in_queue}, f)
                        last_backup = current_time
                        print(f"Backup saved at {time.ctime()}")

                # Clean up
                await browser.close()

    print("Extraction completed. Content saved to llm.txt")
    print("Visited links saved to links_visited.txt")

if __name__ == "__main__":
    asyncio.run(main())
