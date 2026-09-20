"""
`app.py`
Starts the Flask analysis webpage; the app itself lives in app/.
"""
from app import app

if __name__ == "__main__":
    app.run(debug=True)
