import os
import secrets
from datetime import date

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import inspect, select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from database import (
    Base,
    CustomerOrder,
    Orders,
    Product,
    Reservation,
    SessionLocal,
    Users,
    engine,
)

app = Flask(__name__, static_folder='img')
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    MAX_CONTENT_LENGTH=16 * 1024,
)
if not os.environ.get('SECRET_KEY'):
    app.logger.warning(
        'SECRET_KEY is not set; sessions will expire on restart. '
        'Set a stable, random SECRET_KEY before deployment.'
    )

Base.metadata.create_all(engine)


def initialize_order_schema():
    order_columns = {
        column['name'] for column in inspect(engine).get_columns('orders')
    }
    if 'customer_order_id' not in order_columns:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                'ALTER TABLE orders ADD COLUMN customer_order_id '
                'INTEGER REFERENCES customer_orders(id)'
            )


MENU_ITEMS = (
    {
        'name': 'Ukrainian Borsch',
        'price': 180,
        'category': 'Traditional soup',
        'description': 'Beetroot soup with tender vegetables, served with a spoonful of sour cream.',
        'image': 'borsch.jpg',
    },
    {
        'name': 'Varenyky',
        'price': 220,
        'category': 'Homemade favorite',
        'description': 'Soft dumplings filled with potato and served with golden onions and sour cream.',
        'image': 'varenyky.jpg',
    },
    {
        'name': 'Pelmeni',
        'price': 240,
        'category': 'Hearty classic',
        'description': 'Tender dumplings with a savory filling, finished with butter and fresh herbs.',
        'image': 'pelmeni.jpg',
    },
    {
        'name': 'Salo & Rye Bread',
        'price': 150,
        'category': 'To share',
        'description': 'A Ukrainian favorite with dark rye bread, garlic, and a touch of fresh herbs.',
        'image': 'salo.jpg',
    },
    {
        'name': 'Homemade Kvas',
        'price': 75,
        'category': 'Traditional drink',
        'description': 'A refreshing, lightly sparkling fermented bread drink, served chilled.',
        'image': 'kvas.jpg',
    },
)


def initialize_menu():
    product_columns = {
        column['name'] for column in inspect(engine).get_columns('products')
    }
    with engine.begin() as connection:
        if 'description' not in product_columns:
            connection.exec_driver_sql(
                "ALTER TABLE products ADD COLUMN description VARCHAR(500) NOT NULL DEFAULT ''"
            )
        if 'image' not in product_columns:
            connection.exec_driver_sql(
                "ALTER TABLE products ADD COLUMN image VARCHAR(100) NOT NULL DEFAULT ''"
            )

    with SessionLocal() as db:
        existing_names = set(db.scalars(select(Product.name)))
        for item in MENU_ITEMS:
            if item['name'] not in existing_names:
                db.add(Product(**item))
        db.commit()


initialize_menu()
initialize_order_schema()


def csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']


app.jinja_env.globals['csrf_token'] = csrf_token


@app.before_request
def load_user_and_validate_csrf():
    if request.method == 'POST':
        expected_token = session.get('csrf_token')
        submitted_token = request.form.get('csrf_token', '')
        if not expected_token or not secrets.compare_digest(
            expected_token.encode('utf-8'), submitted_token.encode('utf-8')
        ):
            abort(400, description='Invalid or expired form. Reload the page and try again.')

    g.user = None
    user_id = session.get('user_id')
    if user_id is not None:
        with SessionLocal() as db:
            g.user = db.get(Users, user_id)
        if g.user is None:
            session.clear()


@app.route('/')
def index():
    return render_template('index.html')

@app.route("/position/<string:name>")
@app.route("/position/<string:name>", methods=['POST'])
def position(name):
    with SessionLocal() as db:
        product = db.scalar(select(Product).where(Product.name == name))
        if product is None:
            abort(404)

        if request.method == 'POST':
            if g.user is None:
                flash('Please log in to add items to your cart.', 'warning')
                return redirect(url_for('login'))

            quantity_value = request.form.get('quantity', '')
            try:
                quantity = int(quantity_value)
            except ValueError:
                quantity = 0

            if quantity < 1 or quantity > 99:
                flash('Choose a quantity between 1 and 99.', 'danger')
                return redirect(url_for('position', name=product.name))

            order = db.scalar(
                select(Orders).where(
                    Orders.user_id == g.user.id,
                    Orders.product_id == product.id,
                    Orders.customer_order_id.is_(None),
                )
            )
            if order is None:
                db.add(Orders(
                    user_id=g.user.id,
                    product_id=product.id,
                    quantity=quantity,
                ))
            else:
                order.quantity += quantity
            db.commit()
            flash(f'Added {quantity} × {product.name} to your cart.', 'success')
            return redirect(url_for('orders'))

    return render_template('position.html', product=product)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if g.user is not None:
        return redirect(url_for('index'))

    username = ''
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirmation = request.form.get('confirm_password', '')

        if not 3 <= len(username) <= 100:
            error = 'Username must be between 3 and 100 characters.'
        elif not 8 <= len(password) <= 128:
            error = 'Password must be between 8 and 128 characters.'
        elif password != confirmation:
            error = 'Passwords do not match.'
        else:
            with SessionLocal() as db:
                user = db.scalar(select(Users).where(Users.username == username))
                if user is not None:
                    error = 'That username is already taken.'
                else:
                    db.add(Users(
                        username=username,
                        password=generate_password_hash(password),
                    ))
                    try:
                        db.commit()
                    except IntegrityError:
                        db.rollback()
                        if db.scalar(select(Users).where(Users.username == username)) is None:
                            raise
                        error = 'That username is already taken.'
                    else:
                        flash('Account created. Please log in.', 'success')
                        return redirect(url_for('login'))

    return render_template('register.html', error=error, username=username)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user is not None:
        return redirect(url_for('index'))

    username = ''
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not 3 <= len(username) <= 100 or not 8 <= len(password) <= 128:
            error = 'Invalid username or password.'
        else:
            with SessionLocal() as db:
                user = db.scalar(select(Users).where(Users.username == username))
                if user is None or not check_password_hash(user.password, password):
                    error = 'Invalid username or password.'
                else:
                    session.clear()
                    session['user_id'] = user.id
                    flash('You are now logged in.', 'success')
                    return redirect(url_for('index'))

    return render_template('login.html', error=error, username=username)


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))


@app.route('/menu')
def menu():
    with SessionLocal() as db:
        products = db.scalars(select(Product).order_by(Product.id)).all()
    return render_template('menu.html', products=products)


@app.route('/reservations', methods=['GET', 'POST'])
def reservations():
    if g.user is None:
        flash('Please log in to book a table.', 'warning')
        return redirect(url_for('login'))

    if request.method == 'POST':
        reservation_date_value = request.form.get('reservation_date', '')
        number_of_people_value = request.form.get('number_of_people', '')
        try:
            reservation_date = date.fromisoformat(reservation_date_value)
            number_of_people = int(number_of_people_value)
        except ValueError:
            flash('Enter a valid reservation date and number of guests.', 'danger')
        else:
            if reservation_date < date.today():
                flash('Reservation date must be today or later.', 'danger')
            elif not 1 <= number_of_people <= 20:
                flash('Choose between 1 and 20 guests.', 'danger')
            else:
                with SessionLocal() as db:
                    db.add(Reservation(
                        user_id=g.user.id,
                        reservation_date=reservation_date,
                        number_of_people=number_of_people,
                    ))
                    db.commit()
                flash('Your table reservation has been saved.', 'success')
                return redirect(url_for('reservations'))

    with SessionLocal() as db:
        user_reservations = db.scalars(
            select(Reservation)
            .where(Reservation.user_id == g.user.id)
            .order_by(Reservation.reservation_date, Reservation.id)
        ).all()

    return render_template(
        'reservations.html',
        reservations=user_reservations,
        minimum_date=date.today().isoformat(),
    )


@app.route('/cart/remove/<int:order_id>', methods=['POST'])
def remove_from_cart(order_id):
    if g.user is None:
        flash('Please log in to update your cart.', 'warning')
        return redirect(url_for('login'))

    with SessionLocal() as db:
        order = db.scalar(
            select(Orders).where(
                Orders.id == order_id,
                Orders.user_id == g.user.id,
                Orders.customer_order_id.is_(None),
            )
        )
        if order is None:
            flash('That item is not in your cart.', 'warning')
        elif order.quantity > 1:
            order.quantity -= 1
            db.commit()
            flash(f'Removed one {order.product.name} from your cart.', 'success')
        else:
            product_name = order.product.name
            db.delete(order)
            db.commit()
            flash(f'Removed {product_name} from your cart.', 'success')

    return redirect(url_for('orders'))


@app.route('/create_order', methods=['GET', 'POST'])
def create_order():
    if g.user is None:
        flash('Please log in to place an order.', 'warning')
        return redirect(url_for('login'))

    with SessionLocal() as db:
        cart_items = db.scalars(
            select(Orders)
            .options(selectinload(Orders.product))
            .where(
                Orders.user_id == g.user.id,
                Orders.customer_order_id.is_(None),
            )
            .order_by(Orders.id)
        ).all()

        if request.method == 'POST':
            if not cart_items:
                flash('Your cart is empty.', 'warning')
                return redirect(url_for('orders'))

            customer_order = CustomerOrder(user_id=g.user.id)
            db.add(customer_order)
            db.flush()
            for item in cart_items:
                item.customer_order_id = customer_order.id
            db.commit()
            flash('Your order has been placed.', 'success')
            return redirect(url_for('my_order', order_id=customer_order.id))

        total = sum(
            (item.product.price * item.quantity for item in cart_items),
            start=0,
        )

    return render_template(
        'create_order.html',
        cart_items=cart_items,
        total=total,
    )


@app.route('/my_order/<int:order_id>')
def my_order(order_id):
    if g.user is None:
        flash('Please log in to view your order.', 'warning')
        return redirect(url_for('login'))

    with SessionLocal() as db:
        customer_order = db.scalar(
            select(CustomerOrder)
            .options(selectinload(CustomerOrder.items).selectinload(Orders.product))
            .where(
                CustomerOrder.id == order_id,
                CustomerOrder.user_id == g.user.id,
            )
        )
        if customer_order is None:
            abort(404)
        total = sum(
            (item.product.price * item.quantity for item in customer_order.items),
            start=0,
        )

    return render_template(
        'my_order.html',
        customer_order=customer_order,
        total=total,
    )


@app.route('/my_orders')
def my_orders():
    if g.user is None:
        flash('Please log in to view your orders.', 'warning')
        return redirect(url_for('login'))

    with SessionLocal() as db:
        customer_orders = db.scalars(
            select(CustomerOrder)
            .options(selectinload(CustomerOrder.items).selectinload(Orders.product))
            .where(CustomerOrder.user_id == g.user.id)
            .order_by(CustomerOrder.created_at.desc(), CustomerOrder.id.desc())
        ).all()
        order_summaries = [
            {
                'order': customer_order,
                'total': sum(
                    (
                        item.product.price * item.quantity
                        for item in customer_order.items
                    ),
                    start=0,
                ),
            }
            for customer_order in customer_orders
        ]

    return render_template('my_orders.html', order_summaries=order_summaries)


@app.route('/orders')
def orders():
    if g.user is None:
        flash('Please log in to view your cart.', 'warning')
        return redirect(url_for('login'))

    with SessionLocal() as db:
        cart_items = db.scalars(
            select(Orders)
            .options(selectinload(Orders.product))
            .where(
                Orders.user_id == g.user.id,
                Orders.customer_order_id.is_(None),
            )
            .order_by(Orders.id)
        ).all()
        total = sum(
            (item.product.price * item.quantity for item in cart_items),
            start=0,
        )
        cart_summary = [
            {
                'product': item.product.name,
                'quantity': item.quantity,
                'subtotal': str(item.product.price * item.quantity),
            }
            for item in cart_items
        ]
        app.logger.info('Cart contents: %s | total=%s', cart_summary, total)
    return render_template('cart.html', cart_items=cart_items, total=total)


if __name__ == '__main__':
    app.run(debug=True)