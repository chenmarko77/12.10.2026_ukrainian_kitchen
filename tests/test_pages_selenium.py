import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By


@pytest.fixture(scope="session")
def selenium_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--window-size=1280,900")
    options.page_load_strategy = "eager"
    driver = webdriver.Chrome(options=options)
    yield driver
    driver.quit()


@pytest.mark.parametrize(
    ("path", "title", "heading"),
    (
        ("/", "Home | Food Shop", "Main page"),
        ("/menu", "Menu | Food Shop", "Our Ukrainian Menu"),
        ("/login", "Login | Food Shop", "Login"),
        ("/register", "Register | Food Shop", "Create an account"),
    ),
)
def test_public_pages_have_titles_headings_and_landmarks(
    selenium_driver: webdriver.Chrome,
    browser_server: str,
    path: str,
    title: str,
    heading: str,
):
    selenium_driver.get(f"{browser_server}{path}")

    assert selenium_driver.title == title
    assert len(selenium_driver.find_elements(By.XPATH, f"//h1[normalize-space()='{heading}']")) == 1
    assert len(
        selenium_driver.find_elements(
            By.CSS_SELECTOR,
            'nav[aria-label="Main navigation"]',
        )
    ) == 1
    assert len(selenium_driver.find_elements(By.TAG_NAME, "main")) == 1


def test_menu_links_open_product_pages_and_images_are_descriptive(
    selenium_driver: webdriver.Chrome,
    browser_server: str,
):
    selenium_driver.get(f"{browser_server}/menu")
    cards = selenium_driver.find_elements(By.CSS_SELECTOR, "a.menu-card-link")
    assert len(cards) == 5

    images = selenium_driver.find_elements(By.CSS_SELECTOR, ".menu-card img")
    assert images
    for image in images:
        assert image.get_attribute("alt")
        assert image.get_property("complete")
        assert image.get_property("naturalWidth") > 0

    product_name = cards[0].find_element(By.TAG_NAME, "h2").text
    cards[0].click()
    assert selenium_driver.find_element(By.TAG_NAME, "h1").text == product_name
    assert selenium_driver.find_element(
        By.CSS_SELECTOR,
        ".position-image",
    ).get_attribute("alt") == product_name


def test_auth_forms_expose_labeled_required_fields(
    selenium_driver: webdriver.Chrome,
    browser_server: str,
):
    selenium_driver.get(f"{browser_server}/login")
    for field_id in ("username", "password"):
        assert selenium_driver.find_element(By.ID, field_id).get_attribute("required") is not None
    assert len(selenium_driver.find_elements(By.NAME, "csrf_token")) == 1

    selenium_driver.get(f"{browser_server}/register")
    for field_id in ("username", "password", "confirm_password"):
        assert selenium_driver.find_element(By.ID, field_id).get_attribute("required") is not None
    assert len(selenium_driver.find_elements(By.NAME, "csrf_token")) == 1
