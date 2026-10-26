import pytest
from playwright.sync_api import Page, sync_playwright


@pytest.fixture(scope="session")
def playwright_browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        yield browser
        browser.close()


@pytest.fixture
def page(playwright_browser):
    page = playwright_browser.new_page()
    yield page
    page.close()


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
    page: Page,
    browser_server: str,
    path: str,
    title: str,
    heading: str,
):
    response = page.goto(f"{browser_server}{path}", wait_until="domcontentloaded")

    assert response is not None and response.status == 200
    assert page.title() == title
    assert page.get_by_role("heading", name=heading, level=1).count() == 1
    assert page.get_by_role("navigation", name="Main navigation").count() == 1
    assert page.get_by_role("main").count() == 1


def test_menu_links_open_product_pages_and_images_are_descriptive(
    page: Page,
    browser_server: str,
):
    page.goto(f"{browser_server}/menu", wait_until="domcontentloaded")
    cards = page.locator("a.menu-card-link")
    assert cards.count() == 5

    image_data = page.locator(".menu-card img").evaluate_all(
        "(images) => images.map((image) => ({alt: image.alt, complete: image.complete, width: image.naturalWidth}))"
    )
    assert all(image["alt"] and image["complete"] and image["width"] > 0 for image in image_data)

    product_name = cards.first.locator("h2").inner_text()
    cards.first.click()
    assert page.get_by_role("heading", name=product_name, level=1).count() == 1
    assert page.locator(".position-image").get_attribute("alt") == product_name


def test_auth_forms_expose_labeled_required_fields(
    page: Page,
    browser_server: str,
):
    page.goto(f"{browser_server}/login", wait_until="domcontentloaded")
    assert page.get_by_label("Username").get_attribute("required") is not None
    assert page.get_by_label("Password").get_attribute("required") is not None
    assert page.locator('input[name="csrf_token"]').count() == 1

    page.goto(f"{browser_server}/register", wait_until="domcontentloaded")
    for label in ("Username", "Password", "Confirm password"):
        assert page.get_by_label(label, exact=True).get_attribute("required") is not None
    assert page.locator('input[name="csrf_token"]').count() == 1
