from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker, mapped_column, Mapped

engine = create_engine("sqlite:///foodshop.db")    
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

class Base(DeclarativeBase):
    pass

class Users(Base):
    __tablename__ = "users"

    orders: Mapped[list["Orders"]] = relationship("Orders", back_populates="user") 
    customer_orders: Mapped[list["CustomerOrder"]] = relationship(
        "CustomerOrder", back_populates="user"
    )
    reservations: Mapped[list["Reservation"]] = relationship(
        "Reservation", back_populates="user"
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

class Product(Base):
    __tablename__ = "products"

    orders: Mapped[list["Orders"]] = relationship("Orders", back_populates="product") 

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    image: Mapped[str] = mapped_column(String(100), default="")
    available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class Orders(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    customer_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_orders.id"), nullable=True
    )
    quantity: Mapped[int] = mapped_column()
    user: Mapped["Users"] = relationship("Users", back_populates="orders")
    product: Mapped["Product"] = relationship("Product", back_populates="orders")
    customer_order: Mapped["CustomerOrder | None"] = relationship(
        "CustomerOrder", back_populates="items"
    )


class CustomerOrder(Base):
    __tablename__ = "customer_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    user: Mapped["Users"] = relationship("Users", back_populates="customer_orders")
    items: Mapped[list["Orders"]] = relationship(
        "Orders", back_populates="customer_order"
    )

class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reservation_date: Mapped[date] = mapped_column(Date)
    number_of_people: Mapped[int] = mapped_column()
    user: Mapped["Users"] = relationship("Users", back_populates="reservations")