import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from werkzeug.security import check_password_hash

from database import Base, Orders, Product, Users
from main import app, initialize_menu


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        database_path = Path(self.directory.name) / 'test.db'
        self.engine = create_engine(f'sqlite:///{database_path}')
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.session_patch = patch('main.SessionLocal', self.sessions)
        self.session_patch.start()
        self.config_patch = patch.dict(app.config, TESTING=True, SECRET_KEY='test-secret')
        self.config_patch.start()
        self.client = app.test_client()

    def tearDown(self):
        self.config_patch.stop()
        self.session_patch.stop()
        self.engine.dispose()
        self.directory.cleanup()

    def post_form(self, path, data=None, follow_redirects=False):
        self.client.get('/login')
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        return self.client.post(
            path,
            data={**(data or {}), 'csrf_token': token},
            follow_redirects=follow_redirects,
        )

    def register(self, **overrides):
        data = {
            'username': 'petro',
            'password': 'a strong password',
            'confirm_password': 'a strong password',
        }
        data.update(overrides)
        return self.post_form('/register', data)

    def login(self, password='a strong password'):
        return self.post_form('/login', {'username': 'petro', 'password': password})

    def test_public_pages_and_auth_forms(self):
        for path in ('/', '/menu', '/login', '/register'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertIn(b'autocomplete="current-password"', self.client.get('/login').data)
        self.assertIn(b'name="confirm_password"', self.client.get('/register').data)

    def test_menu_items_seed_once_and_render_database_products(self):
        initialize_menu()
        initialize_menu()
        with self.sessions() as db:
            products = db.scalars(select(Product).order_by(Product.id)).all()
            self.assertEqual(len(products), 5)
            db.add(Product(
                name='Seasonal Soup',
                price=Decimal('99.50'),
                category='Special',
                description='A seasonal test dish.',
                image='borsch.jpg',
            ))
            db.commit()

        response = self.client.get('/menu')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Seasonal Soup', response.data)
        self.assertIn(b'A seasonal test dish.', response.data)
        self.assertIn(b'\xe2\x82\xb499.50', response.data)
        self.assertIn(b'/img/borsch.jpg', response.data)

    def test_position_page_displays_database_product_and_handles_unknown_name(self):
        initialize_menu()
        product = self.client.get('/position/Ukrainian%20Borsch')
        self.assertEqual(product.status_code, 200)
        self.assertIn(b'Ukrainian Borsch', product.data)
        self.assertIn(b'Traditional soup', product.data)
        self.assertIn(b'Beetroot soup with tender vegetables', product.data)
        self.assertIn(b'/img/borsch.jpg', product.data)

        menu = self.client.get('/menu')
        self.assertIn(
            b'<a class="menu-card-link" href="/position/Ukrainian%20Borsch">\n'
            b'\t\t\t<article class="card menu-card">',
            menu.data,
        )
        self.assertIn(b'Ukrainian Borsch</h2>', menu.data)
        self.assertEqual(self.client.get('/position/Not%20on%20the%20menu').status_code, 404)

    def test_add_to_cart_requires_login_and_persists_order_for_user(self):
        initialize_menu()
        position = self.client.get('/position/Ukrainian%20Borsch')
        self.assertIn(b'name="quantity"', position.data)
        self.assertIn(b'name="csrf_token"', position.data)

        response = self.post_form(
            '/position/Ukrainian%20Borsch',
            {'quantity': '2'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/login'))
        self.assertTrue(self.client.get('/orders').location.endswith('/login'))
        self.register()
        self.login()
        self.client.get('/position/Ukrainian%20Borsch')

        with self.client.session_transaction() as session:
            csrf = session['csrf_token']
        response = self.client.post(
            '/position/Ukrainian%20Borsch',
            data={'csrf_token': csrf, 'quantity': '2'},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Added 2', response.data)
        self.assertIn(b'Your Cart', response.data)
        self.assertIn(b'2</td>', response.data)
        self.assertIn(b'\xe2\x82\xb4360.00', response.data)

        response = self.client.post(
            '/position/Ukrainian%20Borsch',
            data={'csrf_token': csrf, 'quantity': '3'},
            follow_redirects=True,
        )
        self.assertIn(b'5</td>', response.data)
        with self.sessions() as db:
            orders = db.scalars(select(Orders)).all()
            self.assertEqual(len(orders), 1)
            self.assertEqual(orders[0].quantity, 5)

    def test_add_to_cart_rejects_invalid_quantities(self):
        initialize_menu()
        self.register()
        self.login()
        self.client.get('/position/Ukrainian%20Borsch')
        with self.client.session_transaction() as session:
            csrf = session['csrf_token']

        for quantity in ('0', '100', 'abc'):
            with self.subTest(quantity=quantity):
                response = self.client.post(
                    '/position/Ukrainian%20Borsch',
                    data={'csrf_token': csrf, 'quantity': quantity},
                    follow_redirects=True,
                )
                self.assertIn(b'Choose a quantity between 1 and 99.', response.data)
        with self.sessions() as db:
            self.assertEqual(db.scalars(select(Orders)).all(), [])

    def test_registration_persists_only_a_password_hash(self):
        response = self.register(username='  petro  ')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/login'))
        with self.sessions() as db:
            user = db.scalar(select(Users).where(Users.username == 'petro'))
            self.assertIsNotNone(user)
            assert user is not None
            self.assertNotEqual(user.password, 'a strong password')
            self.assertTrue(user.password.startswith('scrypt:'))
            self.assertTrue(check_password_hash(user.password, 'a strong password'))
        with self.client.session_transaction() as session:
            self.assertNotIn('user_id', session)

    def test_duplicate_username_does_not_replace_password(self):
        self.register()
        response = self.register(password='different password', confirm_password='different password')
        self.assertIn(b'username is already taken', response.data)
        self.assertEqual(self.login().status_code, 302)

    def test_invalid_registration_creates_no_user(self):
        cases = (
            {'username': ''},
            {'username': 'ab'},
            {'username': 'x' * 101},
            {'password': 'short', 'confirm_password': 'short'},
            {'password': 'x' * 129, 'confirm_password': 'x' * 129},
            {'confirm_password': 'does not match'},
        )
        for data in cases:
            with self.subTest(data=data):
                response = self.register(**data)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'role="alert"', response.data)
                with self.sessions() as db:
                    self.assertIsNone(db.scalar(select(Users)))

    def test_login_sets_session_and_logout_clears_it(self):
        self.register()
        with self.client.session_transaction() as session:
            old_token = session['csrf_token']
            session['unrelated'] = 'old data'
        self.assertEqual(self.login().status_code, 302)
        with self.client.session_transaction() as session:
            self.assertIn('user_id', session)
            self.assertNotIn('unrelated', session)
        home = self.client.get('/')
        self.assertIn(b'Hello, petro', home.data)
        self.assertIn(b'Logout', home.data)
        with self.client.session_transaction() as session:
            self.assertNotEqual(session['csrf_token'], old_token)
        response = self.post_form('/logout', follow_redirects=True)
        self.assertIn(b'You have been logged out.', response.data)
        self.assertNotIn(b'Hello, petro', response.data)
        with self.client.session_transaction() as session:
            self.assertNotIn('user_id', session)

    def test_wrong_password_and_unknown_user_have_same_error(self):
        self.register()
        wrong = self.login(password='wrong password')
        unknown = self.post_form('/login', {
            'username': 'unknown', 'password': 'wrong password',
        })
        for response in (wrong, unknown):
            self.assertIn(b'Invalid username or password.', response.data)
            self.assertNotIn(b'value="wrong password"', response.data)
        with self.client.session_transaction() as session:
            self.assertNotIn('user_id', session)

    def test_missing_login_fields_are_rejected(self):
        response = self.post_form('/login')
        self.assertIn(b'Invalid username or password.', response.data)

    def test_csrf_is_required_for_all_auth_posts(self):
        self.client.get('/register')
        for path in ('/login', '/register', '/logout'):
            for token in (None, 'invalid', 'non-ascii-\u00e9'):
                with self.subTest(path=path, token=token):
                    data = {} if token is None else {'csrf_token': token}
                    self.assertEqual(self.client.post(path, data=data).status_code, 400)

    def test_logout_does_not_accept_get(self):
        self.assertEqual(self.client.get('/logout').status_code, 405)

    def test_authenticated_users_redirect_away_from_auth_forms(self):
        self.register()
        self.login()
        for path in ('/login', '/register'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith('/'))

    def test_deleted_user_session_is_cleared(self):
        self.register()
        self.login()
        with self.sessions() as db:
            user = db.scalar(select(Users))
            assert user is not None
            db.delete(user)
            db.commit()
        self.assertEqual(self.client.get('/').status_code, 200)
        with self.client.session_transaction() as session:
            self.assertNotIn('user_id', session)

    def test_username_is_escaped_in_navigation(self):
        self.register(username='<script>alert(1)</script>')
        self.post_form('/login', {
            'username': '<script>alert(1)</script>',
            'password': 'a strong password',
        })
        home = self.client.get('/')
        self.assertIn(b'&lt;script&gt;', home.data)
        self.assertNotIn(b'<script>alert(1)</script>', home.data)


if __name__ == '__main__':
    unittest.main()