# PINSystem

A starter full-stack web application for a machinery manufacturer built with FastAPI, Jinja2 templates, and SQLite.

## Project structure

```text
PINSystem/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── static/
│   │   └── styles.css
│   └── templates/
│       └── index.html
├── database/
│   ├── *.csv
│   └── pin_system.db
├── init_db.py
├── requirements.txt
└── README.md
```

## Getting started

1. Create and activate a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Initialize the SQLite database from the CSV files: `python init_db.py`
4. Start the app: `uvicorn app.main:app --reload`

## Next steps

- Add authentication and RBAC for Engineer, Purchaser, Production, Client, and Manager roles.
- Implement BOM, sourcing, order, and assembly workflows.
- Add photo uploads, order placement, and replacement-part lookup logic.
