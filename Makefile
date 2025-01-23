run-dev:
	FLASK_ENV=development FLASK_APP=landrush uv run flask run -p 5001 --extra-files=landrush/schema.sql
