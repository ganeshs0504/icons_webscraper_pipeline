from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from unidecode import unidecode
import requests
from bs4 import BeautifulSoup
import pandas as pd


# Setting up selenium to be run on a dockerized container
chrome_options = webdriver.ChromeOptions()
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--window-size=1920,1080')
chrome_options.add_argument('--ignore-ssl-errors=yes')
chrome_options.add_argument('--ignore-certificate-errors')
chrome_options.add_argument('--headless')
chrome_options.add_argument('--disable-gpu')
driver = webdriver.Remote(command_executor='http://selenium-hub:4444/wd/hub', options=chrome_options)


driver.get("https://www.icons.com/players/a-k.html")

# Defining XPATH used as dictionary
xpaths = {
    'accept_cookies_btn': "//button[@title='Accept all cookies']",
    'player_grid_items': "//div[contains(@class, 'products-grid')]//li/div/a",
    'curr_product_count_xpath': "//p/span[@x-text='productsProgress']",
    'total_product_count_xpath': "//p/span[@x-text='productsTotal']",
    'load_more_btn': "//button[contains(text(), 'Load More Items')]",
    'product_listings': "//div[contains(@class, 'products-grid')]//*[contains(@class, 'product')]/a"
}

# Accepting the cookie button if its avialable
try:
    cookie_button = WebDriverWait(driver, 5).until(
        EC.element_to_be_clickable((By.XPATH, xpaths['accept_cookies_btn']))
    )
    cookie_button.click()
    print("Cookies accepted!")

except Exception as e:
    print(f"Could not find or click the cookie button: {e}")


players = driver.find_elements(By.XPATH, xpaths['player_grid_items'])
player_name_link = {}

# Getting name and link for all the players with surname A-K
for player in players:
    player_name = player.text.strip()
    player_url = player.get_attribute("href")

    # Filtering surnames between A-C
    if player_name.split()[-1][0].upper() in 'ABC':
        player_name_link[player_name] = player_url

# Generating product URLs for signed By {player_name} dynamically
for name, url in player_name_link.items():
    param_name = unidecode(name).replace(" ", "+")
    products_url = f"{url}?player_names={param_name}"
    player_name_link[name] = products_url



final_links = {}

# Loop through all the dynamically generated links to get product listings for each players
for name, signed_url in player_name_link.items():
    driver.get(signed_url)
    try:
        curr_item_count = int(driver.find_element(By.XPATH, xpaths['curr_product_count_xpath']).text)
        total_item_count = int(driver.find_element(By.XPATH, xpaths['total_product_count_xpath']).text)
    except Exception:
        print(f"skipping player {name} as there are no products to display")
        pass
    # Loop till all the products are shown for each player by clicking load more button
    while curr_item_count != total_item_count:
        driver.find_element(By.XPATH, xpaths['load_more_btn']).click()
        
        WebDriverWait(driver, 10).until(
            lambda d: int(d.find_element(By.XPATH, xpaths['curr_product_count_xpath']).text) != curr_item_count
        )
        
        curr_item_count = int(driver.find_element(By.XPATH, xpaths['curr_product_count_xpath']).text)
        total_item_count = int(driver.find_element(By.XPATH, xpaths['total_product_count_xpath']).text)

    product_list = driver.find_elements(By.XPATH, xpaths['product_listings'])
    product_links = []
    for product in product_list:
        product_links.append(product.get_attribute("href"))
    final_links[name] = product_links



driver.close()



# BeautifulSoup code for getting product details for each possible products for all the selected players
final_table = []
for name, product_links in final_links.items():
    for product_link in product_links:
        page = requests.get(product_link)
        soup = BeautifulSoup(page.text, 'html')
    
        price = soup.find('meta', itemprop='price')['content']
        title = soup.find("h1", class_='page-title').get_text(strip=True)

        stock = soup.find('p', title='Availability').get_text(strip=True)
        
        product_data = {
            'player_name': name,
            'product_link': product_link,
            'product_title': title,
            'price': float(price),
            'availability': False if stock == 'Out of Stock' else True
        }
        table = soup.find('table', class_='additional-attributes')
        for row in table.find_all('tr'):
            for col in row.find('td'):
                key = row.find('th').get_text(strip=True)
                value = col.get_text(strip=True)
                product_data[key] = value
        final_table.append(product_data)

# Converting the populated details to dataframe and then storing as CSV
df = pd.DataFrame(final_table)
df['price'] = pd.to_numeric(df['price'], errors='coerce')
df.to_csv("/app/output/products.csv", index=False)

# Finding the most common product among all the players for a fair comparison to compute signature worthiness
df['size'] = df[['Presentation size', 'Photo size']].bfill(axis=1).iloc[:, 0]
product_counts = df.groupby(['Presentation type', 'Product type(s)', 'size'])\
    .agg(player_count=('player_name', 'nunique'), product_count=('player_name', 'count'))\
    .reset_index()
most_common = product_counts.sort_values(by='player_count', ascending=False).iloc[0]
filtered_df = df[
    (df['Presentation type'] == most_common['Presentation type']) &
    (df['Product type(s)'] == most_common['Product type(s)']) &
    (df['size'] == most_common['size'])
]
signature_value = filtered_df.groupby('player_name')['price'].mean().reset_index()
signature_value = signature_value.rename(columns={'price': 'signature_worth'})
signature_value = signature_value.sort_values(by='signature_worth', ascending=False)
signature_value.player_name
signature_value.to_csv('/app/output/signature_worth.csv', index=False)

# Calculating portfolio value for each players
portfolio_value = df.groupby('player_name')['price'].sum().reset_index()
portfolio_value.to_csv('/app/output/portfolio_values.csv', index=False)

# Players excluded from the signature worthiness list as they dont have enough data to be fairly compared
excluded_players = df[~df['player_name'].isin(signature_value['player_name'])]
excluded_players[['player_name']].drop_duplicates().to_csv('/app/output/excluded_players.csv', index=False)

# Signature worthiness calculation for all players by highest priced product
signature_value_on_max_price = df.groupby('player_name')['price'].max().reset_index()
signature_value_on_max_price = signature_value_on_max_price.rename(columns={'price': 'signature_worth'})
signature_value_on_max_price = signature_value_on_max_price.sort_values(by='signature_worth', ascending=False)
signature_value_on_max_price.to_csv('/app/output/signature_worth_by_max_price.csv', index=False)