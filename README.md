# Fire Safety Register

A web-based Fire Safety Equipment Inspection & Expiry Register with Machine Learning Risk Prediction and Google Email Authentication. This application tracks fire safety equipment, records inspection history, alerts on upcoming or overdue inspections, and uses ML models to predict maintenance risks.

---

## 🚀 Features

- **Google Email Sign-In & Auth**: Secure authentication supporting Google Email Login (Google Identity Services GIS) & Standard Officer Email login.
- **Dashboard**: Summary metrics for total, overdue, approaching, and good-status equipment.
- **Equipment Management**: Add, search, filter, and inspect fire safety equipment across multiple building locations.
- **Inspection History**: Log inspections with pass/fail/repair statuses and automatic next-due calculation.
- **ML Risk Prediction**: Automated risk assessment trained on inspection history patterns.
- **REST APIs**: JSON endpoints for equipment status (`/api/equipment`), risk predictions (`/api/predictions`), and Google Auth (`/api/auth/google`).

---

## 📋 Prerequisites

- **Python 3.8+**
- **pip** (Python package installer)

---

## 🛠️ Installation & Setup

1. **Navigate to project directory**:
   ```bash
   cd d:\fire-safety-register
   ```

2. **(Optional) Create and activate a Virtual Environment**:
   - **Windows**:
     ```cmd
     python -m venv venv
     venv\Scripts\activate
     ```
   - **macOS / Linux**:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

## 🌱 Data Seeding & Model Training (Optional)

To seed sample building locations, equipment, inspection history, and train the risk prediction model:

```bash
python seed_data.py
```

---

## ▶️ Running the Application

To start the Flask development server:

```bash
python app.py
```

The server will start running at:
👉 **[http://127.0.0.1:5000](http://127.0.0.1:5000)** or **[http://localhost:5000](http://localhost:5000)**

*(Note: Unauthenticated users will automatically be redirected to the `/login` page).*

---

## 🔐 Google Authentication Configuration (Optional)

To use your custom Google OAuth Client ID, set the environment variable before starting the app:

- **Windows PowerShell**:
  ```powershell
  $env:GOOGLE_CLIENT_ID="your_google_client_id_here.apps.googleusercontent.com"
  python app.py
  ```
- **Windows Command Prompt**:
  ```cmd
  set GOOGLE_CLIENT_ID=your_google_client_id_here.apps.googleusercontent.com
  python app.py
  ```

---

## 🔗 Endpoints

| Endpoint | Method | Access | Description |
| :--- | :--- | :--- | :--- |
| `/login` | `GET` / `POST` | Public | Login page with Google Email Sign-In and standard email login |
| `/logout` | `GET` | Authenticated | Clears user session and logs out |
| `/api/auth/google` | `POST` | Public | Google Identity Services OAuth credential verification endpoint |
| `/api/equipment` | `GET` | Authenticated | Returns list of all equipment with status details |
| `/api/predictions` | `GET` | Authenticated | Returns ML risk prediction probabilities |
| `/retrain` | `GET` | Authenticated | Triggers retraining of the risk prediction model |

---

## 📁 Project Structure

```text
fire-safety-register/
├── app.py              # Main Flask application with auth middleware & routes
├── database.py         # SQLite database schema (equipment, inspections, users)
├── model.py            # Machine Learning (scikit-learn) model for risk prediction
├── seed_data.py        # Script to generate sample data and train initial model
├── requirements.txt    # Project dependencies
├── fire_safety.db      # SQLite database file (created automatically)
├── risk_model.pkl      # Saved ML model binary
├── static/             # Static CSS, JS, and asset files
└── template/           # HTML templates (base, login, index, equipment, etc.)
```
