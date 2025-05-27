# DATA Dashboards AI

This project is a web application designed for visualizing and analyzing marketing and business data. It features interactive dashboards for various datasets and includes an integrated AI chat assistant (powered by Gemini) to gain insights from the data using natural language queries.

## Core Features

*   **Password-Protected Access:** Ensures that only authorized users can access the application.
*   **Multi-Brand Dashboards:** Capable of displaying data from various sources/brands. Currently configured for:
    *   **Chiesi [Budget]:** Visualizes weekly budget delta between Google Ads and Adform, including forecasts and trend analysis.
    *   **Chiesi [Sessions]:** Displays weekly user session data, Year-To-Date (YTD) delta, paid contribution percentages, and allows for brand-to-brand comparisons.
    *   (Support for GUM and TTT dashboards is present in the code but currently commented out).
*   **AI Chat Assistant:** Integrates with Google's Gemini model, allowing users to ask questions about the displayed data in natural language and receive AI-generated insights.
*   **Rich Data Visualizations:** Utilizes Altair and Plotly libraries to create interactive charts and graphs for effective data representation.

## Project Structure

The project is organized as follows:

```
.
├── .devcontainer/        # Configuration for development containers
├── .streamlit/           # Streamlit-specific configuration (e.g., config.toml)
├── app.py                # Main Streamlit application: handles UI, page navigation, and AI chat integration.
├── chiesi_budget.py      # Module for loading and rendering the Chiesi [Budget] dashboard.
├── chiesi_sessions.py    # Module for loading and rendering the Chiesi [Sessions] dashboard.
├── gum.py                # Module for the GUM brand dashboard (currently inactive).
├── ttt.py                # Module for the TTT brand dashboard (currently inactive).
├── create_update_db.py   # Script to import data from local Excel files into the PostgreSQL database.
├── update_db_sheets.py   # Preferred script to import data from Google Sheets or local Excel files to PostgreSQL.
├── update_db.yml         # GitHub Actions workflow for potentially automating database updates.
├── requirements.txt      # Python dependencies for the project.
├── style.css             # Custom CSS styles for the application.
├── imgs/                 # Directory containing logos and other image assets.
└── README.md             # This file.
```

## Data Backend and Update Process

### Data Storage

The application relies on a **PostgreSQL** database to store all the data visualized in the dashboards. Key tables include:

*   `chiesi_weekly_budget`: Stores weekly budget data for Chiesi.
*   `chiesi_weekly_sessions`: Stores weekly session data for Chiesi.
*   `gum_monthly_uv`: Stores monthly unique visitor data for GUM.
*   `ttt_weekly_cps`: Stores weekly cost-per-sale data for TTT.

### Data Updates

Data is imported into the PostgreSQL database from external sources (Excel files or Google Sheets).

*   **Scripts:**
    *   `update_db_sheets.py`: This is the primary script used for updating the database. It can fetch data from either Google Sheets (requiring Google Cloud credentials) or local Excel files. It handles data parsing, cleaning, column standardization, and upserting data into the database (updating existing open periods and adding new data).
    *   `create_update_db.py`: An earlier version of the update script, primarily focused on importing data from local Excel files.

*   **Automation:**
    *   The `update_db.yml` file defines a **GitHub Actions workflow** that automates the data update process.
    *   This workflow runs daily (at 5:00 UTC) or can be triggered manually.
    *   It executes a command specified in `command_update_db_monitoring.txt` (which typically runs `update_db_sheets.py`) to refresh the database with the latest data from the configured Google Sheet.

*   **Process Highlights:**
    *   **Snapshotting:** A `snapshot_date` is recorded with each data ingestion.
    *   **Upsert Logic:** The scripts use an "upsert" mechanism. Data for closed periods (e.g., past weeks/months) is preserved, while data for currently open periods is updated with the latest information.
    *   **Forecasting:** For metrics in open periods, the scripts can calculate a forecast based on the data available to date and the period's duration.

## Setup and Running Instructions

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create a Python Virtual Environment:**
    It's recommended to use a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies:**
    Install all required packages using `pip`:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables / Secrets:**
    The application uses Streamlit secrets and environment variables for configuration. Ensure you have the following set up:

    *   **Streamlit Secrets (`.streamlit/secrets.toml`):**
        Create this file if it doesn't exist.
        ```toml
        # Password for accessing the application
        app_password = "your_strong_password_here"

        # PostgreSQL database connection details
        [postgres]
        host = "your_db_host"
        port = 5432 # or your_db_port
        database = "your_db_name"
        user = "your_db_user"
        password = "your_db_password"

        # Google API Key for Gemini AI
        [google]
        api_key = "your_gemini_api_key"
        ```

    *   **Environment Variables (for data updates):**
        *   `DB_DSN`: The full database connection string (e.g., `postgresql://user:password@host:port/database`). This is used by the update scripts and GitHub Actions.
        *   `GOOGLE_APPLICATION_CREDENTIALS`: Path to your Google Cloud service account JSON key file. This is required if you intend to import data from Google Sheets using `update_db_sheets.py`.
        *   `GOOGLE_CREDS_JSON`: (For GitHub Actions) The content of the Google Cloud service account JSON key file. This is stored as a GitHub secret.

5.  **Run the Database Update Script (Initial Setup / Manual Update):**
    Before running the app for the first time, or to manually update the data, you might need to run the update script. The preferred script is `update_db_sheets.py`.
    *   **Example (using Google Sheets):**
        ```bash
        export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/creds.json"
        export DB_DSN="postgresql://user:password@host:port/database" # Or set in your environment
        python update_db_sheets.py --gsheet-id "your_google_sheet_id" --creds "$GOOGLE_APPLICATION_CREDENTIALS"
        ```
    *   **Example (using local Excel file):**
        ```bash
        export DB_DSN="postgresql://user:password@host:port/database" # Or set in your environment
        python update_db_sheets.py --file "Monitoring Files.xlsx"
        ```
    *(Note: The `command_update_db_monitoring.txt` file might contain the specific command used in the automated workflow, which can serve as a reference.)*

6.  **Run the Streamlit Application:**
    Once the dependencies are installed and the environment is configured (including database setup), you can start the Streamlit application:
    ```bash
    streamlit run app.py
    ```
    The application should then be accessible in your web browser at the URL provided by Streamlit (usually `http://localhost:8501`).

## Key Dependencies

The project relies on several Python libraries, including:

*   **Streamlit (`streamlit`):** For building the interactive web application.
*   **Pandas (`pandas`):** For data manipulation and analysis.
*   **SQLAlchemy (`sqlalchemy`):** For SQL database interactions (used by data import scripts).
*   **psycopg2-binary (`psycopg2-binary`):** PostgreSQL adapter for Python.
*   **Google Generative AI (`google-generativeai`):** For interacting with the Gemini AI model.
*   **Streamlit Chat (`streamlit-chat`):** For creating the chat interface in Streamlit.
*   **Plotly (`plotly`):** For creating interactive charts.
*   **Altair (`altair`):** For declarative statistical visualizations.
*   **Tabulate (`tabulate`):** For creating simple tables (likely used by data import scripts or utilities).
*   **GSpread (`gspread`) & Google Auth (`google-auth`):** For fetching data from Google Sheets (used by `update_db_sheets.py`).

A complete list of dependencies can be found in `requirements.txt`.

## Contributing

Contributions to this project are welcome. If you have suggestions for improvements or bug fixes, please feel free to:

1.  Fork the repository.
2.  Create a new branch for your feature or fix.
3.  Make your changes.
4.  Submit a pull request with a clear description of your changes.
