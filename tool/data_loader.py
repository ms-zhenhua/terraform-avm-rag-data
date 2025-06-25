
import asyncio
import json
import logging
import os
import tarfile
import time
import requests
import shutil

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .utils import AVM_OFFICIAL_URL, ORIGIN_DATA_FILE_PATH, DATA_DIRECTORY_PATH, DOWNLOADED_TAR_PATH, run_tasks, raise_error

def load_modules_info() -> dict[str, dict]:
    logging.info("Loading modules info from AVM official website...")

    with open(ORIGIN_DATA_FILE_PATH, "r", encoding='utf-8') as file:
        origin_data = json.load(file)

    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run in headless mode
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )
    
    try:
        url = AVM_OFFICIAL_URL
        driver.get(url)
        
        # Wait for the page to load - adjust timeout as needed
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, "//h3[contains(text(), 'Published modules')]"))
        )
        
        # Give a little extra time for everything to render
        time.sleep(2)
        logging.info("Page loaded successfully, parsing content...")
        
        # Get the page source after JavaScript has executed
        html_content = driver.page_source
        
        # Parse with BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find the section header
        published_modules_section = soup.find(lambda tag: tag.name in ['h3'] and 'Published modules' in tag.text)
        
        modules_info = {}
        
        if published_modules_section:
            # Look for the details element that contains the table
            details_element = published_modules_section.find_next('details')
            
            if details_element:
                # Find the table within the details element
                modules_table = details_element.find('table')
                
                if modules_table:
                    # Process table rows (skip header row)
                    rows = modules_table.find_all('tr')[1:]  # Skip header
                    for row in rows:
                        cells = row.find_all('td')
                        if cells and len(cells) >= 2:  # We need at least the module name cell (2nd column)
                            # Module name is in the second column
                            module_cell = cells[1]
                            link_tag = module_cell.find('a')
                            module_name = link_tag.get_text(strip=True)
                            # Display name is in the fourth column
                            display_name_cell = cells[3]
                            bold_tag = display_name_cell.find('b')
                            display_name = bold_tag.get_text(strip=True)
                            source_url_cell = cells[2]
                            source_link_tag = source_url_cell.find('a')
                            source_url = source_link_tag.get('href') if source_link_tag else ""
                            if module_name in origin_data:
                                modules_info[module_name] = {
                                    "module_name": module_name,
                                    "display_name": display_name,
                                    "source": origin_data[module_name].get("source", ""),
                                    "git_hub_url": source_url,
                                    "description": origin_data[module_name].get("description", ""),
                                }

                                continue

                            url = link_tag.get('href')
                            driver.get(url)
                            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "title")))
                            time.sleep(2)
                            source = driver.title.split('|')[0].strip()
                            modules_info[module_name] = {
                                "module_name": module_name,
                                "display_name": display_name,
                                "source": source,
                                "git_hub_url": source_url,
                                "description": f"Manages {display_name}",

                            }
                            
                            logging.info(f"load module info: Module Name: {module_name}, Display Name: {display_name}, Source: {source}, GitHub URL: {source_url}")                                            
                                      
        return modules_info 
    finally:
        # Always close the driver
        driver.quit()

def download_the_latest_version_module(module: dict, headers: dict):
    logging.info("Downloading the latest version of module: %s", module['module_name'])
    extract_to = os.path.join(DATA_DIRECTORY_PATH, module['module_name'])
    dest_path = os.path.join(DOWNLOADED_TAR_PATH, f"{module['module_name']}.tar.gz")

    # Download the package
    if not os.path.exists(dest_path):    
        response = requests.get('/'.join([module["git_hub_url"].replace("github.com", "api.github.com/repos"),'releases', 'latest']), headers=headers)
        if response.status_code != 200:
            response = requests.get('/'.join([module["git_hub_url"].replace("github.com", "api.github.com/repos"),'releases']), headers=headers)
            release_info_list = response.json()
            release_info = release_info_list[0]
        else:
            release_info = response.json()
        response = requests.get(release_info["tarball_url"], stream=True, headers=headers)
        response.raise_for_status()
        with open(dest_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
    
    # Extract the downloaded file
    if os.path.exists(extract_to):
        shutil.rmtree(extract_to)
    os.makedirs(extract_to, exist_ok=True)
    with tarfile.open(dest_path, "r:gz") as tar:
        # Run this command to avoid Windows length limitation: Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1
        tar.extractall(path=extract_to)
    
    # re-organize the directory structure
    if len(os.listdir(extract_to)) == 1:
        src = os.path.join(extract_to, os.listdir(extract_to)[0])
        if os.path.isdir(src):
            for entry in os.listdir(src):
                shutil.move(os.path.join(src, entry), extract_to)
            shutil.rmtree(src)

async def download_the_latest_version_modules(modules_info: dict[str, dict]):
    os.environ['PYTHONUTF8'] = '1'  # Enable UTF-8 mode
    os.makedirs(DOWNLOADED_TAR_PATH, exist_ok=True)
    
    token = os.getenv('GITHUB_TOKEN')
    if not token:
        raise_error("GITHUB_TOKEN environment variable is not set. Please set it to your GitHub token.")

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"
    }
    
    tasks = []
    for module in modules_info:
        tasks.append(lambda x=modules_info[module]: download_the_latest_version_module(x, headers))
    await run_tasks(tasks, 10)



async def load_data() -> dict[str, dict]:
    try:
        data = load_modules_info()
    except Exception as e:
        raise_error(f"Failed to load modules info: {e}")
    
    try:
        await download_the_latest_version_modules(data)
    except Exception as e:
        raise_error(f"Failed to download the latest version: {e}")
    
    return data

async def main():
    from utils import DATA_FILE_PATH
    data = await load_data()
    with open(DATA_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=4))
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
    
