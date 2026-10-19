from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker, mapped_column, Mapped

engine = create_engine("sqlite:///foodshop.db")    
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

class Base(DeclarativeBase):
    pass

class Users(Base):
    __tablename__ = "users"

    orders: Mapped[list["Orders"]] = relationship("Orders", back_populates="user") 

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password: Mapped[str] = mapped_column(String(255))

class Product(Base):
    __tablename__ = "products"

    orders: Mapped[list["Orders"]] = relationship("Orders", back_populates="product") 

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    image: Mapped[str] = mapped_column(String(100), default="")

class Orders(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column()
    user: Mapped["Users"] = relationship("Users", back_populates="orders")
    product: Mapped["Product"] = relationship("Product", back_populates="orders")

class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reservation_date: Mapped[date] = mapped_column(Date)
    number_of_people: Mapped[int] = mapped_column()