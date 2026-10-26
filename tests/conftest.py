from threading import Thread

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from werkzeug.serving import make_server


@pytest.fixture(scope="session")
def browser_server(tmp_path_factory):
    import main
    from database import Base, Product

    database_path = tmp_path_factory.mktemp("browser-tests") / "foodshop.db"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with test_sessions() as db:
        db.add_all(Product(**item) for item in main.MENU_ITEMS)
        db.commit()

    original_session_local = main.SessionLocal
    original_testing = main.app.config["TESTING"]
    original_secret_key = main.app.config["SECRET_KEY"]
    main.SessionLocal = test_sessions
    main.app.config.update(TESTING=True, SECRET_KEY="browser-tests-only")

    server = make_server("127.0.0.1", 0, main.app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        main.SessionLocal = original_session_local
        main.app.config.update(
            TESTING=original_testing,
            SECRET_KEY=original_secret_key,
        )
        engine.dispose()
