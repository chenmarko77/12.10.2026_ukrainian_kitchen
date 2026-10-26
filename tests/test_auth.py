import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from werkzeug.security import check_password_hash

from database import Base, CustomerOrder, Orders, Product, Reservation, Users
from main import app, initialize_menu, initialize_order_schema


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

        with self.assertLogs('main', level='INFO') as logs:
            self.client.get('/orders')
        self.assertIn('Ukrainian Borsch', logs.output[0])
        self.assertIn("'quantity': 5", logs.output[0])
        self.assertIn('total=900.00', logs.output[0])

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

    def test_remove_from_cart_decrements_one_and_removes_last_item(self):
        initialize_menu()
        self.register()
        self.login()
        self.client.get('/position/Ukrainian%20Borsch')
        with self.client.session_transaction() as session:
            csrf = session['csrf_token']
        self.client.post(
            '/position/Ukrainian%20Borsch',
            data={'csrf_token': csrf, 'quantity': '5'},
        )

        with self.sessions() as db:
            order = db.scalar(select(Orders))
            assert order is not None
            order_id = order.id

        response = self.client.get('/orders')
        self.assertIn(b'Remove one', response.data)
        response = self.client.post(
            f'/cart/remove/{order_id}',
            data={'csrf_token': csrf},
            follow_redirects=True,
        )
        self.assertIn(b'Removed one Ukrainian Borsch', response.data)
        self.assertIn(b'4</td>', response.data)

        for expected_quantity in (3, 2, 1):
            response = self.client.post(
                f'/cart/remove/{order_id}',
                data={'csrf_token': csrf},
                follow_redirects=True,
            )
            self.assertIn(f'{expected_quantity}</td>'.encode(), response.data)
        response = self.client.post(
            f'/cart/remove/{order_id}',
            data={'csrf_token': csrf},
            follow_redirects=True,
        )
        self.assertIn(b'Removed Ukrainian Borsch', response.data)
        with self.sessions() as db:
            self.assertEqual(db.scalars(select(Orders)).all(), [])
        self.assertIn(b'Your cart is empty.', self.client.get('/orders').data)

    def test_create_order_persists_cart_items_and_clears_cart(self):
        initialize_menu()
        initialize_order_schema()
        self.register()
        self.login()
        self.client.get('/position/Pelmeni')
        with self.client.session_transaction() as session:
            csrf = session['csrf_token']
        self.client.post(
            '/position/Pelmeni',
            data={'csrf_token': csrf, 'quantity': '2'},
        )

        preview = self.client.get('/create_order')
        self.assertEqual(preview.status_code, 200)
        self.assertIn(b'Review Your Order', preview.data)
        self.assertIn(b'Pelmeni', preview.data)
        self.assertIn(b'\xe2\x82\xb4480.00', preview.data)

        response = self.client.post(
            '/create_order',
            data={'csrf_token': csrf},
            follow_redirects=True,
        )
        self.assertIn(b'Your order has been placed.', response.data)
        self.assertIn(b'Order details', response.data)
        self.assertIn(b'Pelmeni', response.data)
        self.assertIn(b'2</td>', response.data)
        self.assertIn(b'\xe2\x82\xb4480.00', response.data)
        order_list = self.client.get('/my_orders')
        self.assertEqual(order_list.status_code, 200)
        self.assertIn(b'Order #1', order_list.data)
        self.assertIn(b'Pelmeni', order_list.data)
        self.assertIn('Pelmeni × 2'.encode(), order_list.data)
        self.assertIn(b'View details', order_list.data)
        with self.sessions() as db:
            customer_order = db.scalar(select(CustomerOrder))
            self.assertIsNotNone(customer_order)
            assert customer_order is not None
            self.assertEqual(customer_order.user_id, 1)
            self.assertIsNotNone(customer_order.created_at)
            items = db.scalars(
                select(Orders).where(Orders.customer_order_id == customer_order.id)
            ).all()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].quantity, 2)

        self.client.post(
            '/position/Pelmeni',
            data={'csrf_token': csrf, 'quantity': '1'},
        )
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(CustomerOrder)).all()), 1)
            cart = db.scalars(
                select(Orders).where(Orders.customer_order_id.is_(None))
            ).all()
            self.assertEqual(len(cart), 1)
            self.assertEqual(cart[0].quantity, 1)

    def test_order_detail_requires_login_and_hides_other_or_missing_orders(self):
        self.assertTrue(self.client.get('/my_order/1').location.endswith('/login'))
        self.assertTrue(self.client.get('/my_orders').location.endswith('/login'))
        self.register()
        self.login()
        self.assertEqual(self.client.get('/my_order/999').status_code, 404)

    def test_create_order_requires_login_and_does_not_create_empty_order(self):
        self.assertTrue(self.client.get('/create_order').location.endswith('/login'))
        self.register()
        self.login()
        self.client.get('/orders')
        with self.client.session_transaction() as session:
            csrf = session['csrf_token']
        response = self.client.post(
            '/create_order',
            data={'csrf_token': csrf},
            follow_redirects=True,
        )
        self.assertIn(b'Your cart is empty.', response.data)
        with self.sessions() as db:
            self.assertEqual(db.scalars(select(CustomerOrder)).all(), [])

    def test_table_reservation_requires_login_and_persists_valid_booking(self):
        self.assertTrue(self.client.get('/reservations').location.endswith('/login'))
        self.register()
        self.login()
        page = self.client.get('/reservations')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'name="reservation_date"', page.data)
        self.assertIn(b'name="number_of_people"', page.data)
        with self.client.session_transaction() as session:
            csrf = session['csrf_token']

        reservation_date = date.today() + timedelta(days=1)
        response = self.client.post(
            '/reservations',
            data={
                'csrf_token': csrf,
                'reservation_date': reservation_date.isoformat(),
                'number_of_people': '4',
            },
            follow_redirects=True,
        )
        self.assertIn(b'Your table reservation has been saved.', response.data)
        self.assertIn(reservation_date.strftime('%d.%m.%Y').encode(), response.data)
        self.assertIn(b'>4</td>', response.data)
        with self.sessions() as db:
            reservation = db.scalar(select(Reservation))
            self.assertIsNotNone(reservation)
            assert reservation is not None
            self.assertEqual(reservation.user_id, 1)
            self.assertEqual(reservation.reservation_date, reservation_date)
            self.assertEqual(reservation.number_of_people, 4)

        invalid_bookings = (
            {'reservation_date': (date.today() - timedelta(days=1)).isoformat(), 'number_of_people': '2'},
            {'reservation_date': reservation_date.isoformat(), 'number_of_people': '0'},
            {'reservation_date': 'not-a-date', 'number_of_people': '2'},
        )
        for booking in invalid_bookings:
            with self.subTest(booking=booking):
                response = self.client.post(
                    '/reservations',
                    data={'csrf_token': csrf, **booking},
                    follow_redirects=True,
                )
                self.assertIn(b'alert-danger', response.data)
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(Reservation)).all()), 1)

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

    def test_menu_management_requires_an_administrator(self):
        anonymous_response = self.client.get('/admin/menu/add')
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertTrue(anonymous_response.location.endswith('/login'))

        self.register()
        self.login()
        self.assertEqual(self.client.get('/admin/menu/add').status_code, 403)
        self.assertNotIn(b'Admin panel', self.client.get('/').data)

    def test_administrator_can_add_menu_item_and_see_it_on_menu(self):
        self.register(username='admin')
        with self.sessions() as db:
            admin = db.scalar(select(Users).where(Users.username == 'admin'))
            assert admin is not None
            admin.is_admin = True
            db.commit()
        self.post_form('/login', {
            'username': 'admin',
            'password': 'a strong password',
        })

        page = self.client.get('/admin/menu/add')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Admin panel', self.client.get('/').data)
        response = self.post_form('/admin/menu/add', {
            'name': 'Deruny',
            'price': '125.50',
            'category': 'Ukrainian classic',
            'description': 'Crispy potato pancakes.',
            'image': 'borsch.jpg',
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Deruny was added to the menu.', response.data)
        self.assertIn(b'Crispy potato pancakes.', response.data)
        with self.sessions() as db:
            product = db.scalar(select(Product).where(Product.name == 'Deruny'))
            assert product is not None
            self.assertEqual(product.price, Decimal('125.50'))
            self.assertEqual(product.image, 'borsch.jpg')

    def test_admin_creation_rejects_invalid_and_duplicate_products(self):
        self.register(username='admin')
        with self.sessions() as db:
            admin = db.scalar(select(Users).where(Users.username == 'admin'))
            assert admin is not None
            admin.is_admin = True
            db.commit()
        self.post_form('/login', {
            'username': 'admin',
            'password': 'a strong password',
        })

        valid_form = {
            'name': 'Test Dish',
            'price': '10.00',
            'category': 'Test',
            'description': '',
            'image': '',
        }
        self.client.get('/admin/menu/add')
        for overrides, expected_error in (
            ({'price': '0'}, b'Price must be between'),
            ({'price': 'not a price'}, b'Enter a valid price.'),
            ({'image': '..\\secret.jpg'}, b'Choose an image file'),
        ):
            with self.subTest(overrides=overrides):
                response = self.post_form(
                    '/admin/menu/add',
                    {**valid_form, **overrides},
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected_error, response.data)

        self.post_form('/admin/menu/add', valid_form)
        duplicate = self.post_form('/admin/menu/add', valid_form)
        self.assertIn(b'A menu item with this name already exists.', duplicate.data)

    def test_make_admin_command_promotes_existing_user(self):
        self.register()
        result = app.test_cli_runner().invoke(args=['make-admin', 'petro'])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('Administrator access granted', result.output)
        with self.sessions() as db:
            user = db.scalar(select(Users).where(Users.username == 'petro'))
            assert user is not None
            self.assertTrue(user.is_admin)


if __name__ == '__main__':
    unittest.main()