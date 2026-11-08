# 🧾 Expense Tracker PWA with AI Receipt Analysis

A modern, responsive Progressive Web App (PWA) built with Flask and Tailwind CSS, featuring automated receipt itemization and tax-excluded financial breakdowns powered by Google GenAI and Google Cloud Run.

---

## ✨ Key Features

- **Unified Search & Filtering:** Filter expenses simultaneously by month and search query (matching store names, product names, or categories).
- **Precise Financial Terminology:** Clear distinction between **商品合計 (Tax-Excluded Item Total)** and **消費税 (Consumption Tax)** across summary cards, donut center overlays, and hover tooltips.
- **Interactive Donut Chart:** Powered by Chart.js with a floating center total overlay.
- **Inline AI Receipt Analysis:** Expandable accordion rows that show itemized receipt breakdowns instantly without modal interruptions.
- **Cloud-Native Deployment:** Containerized and deployed seamlessly on **Google Cloud Run** backed by **Google Firestore**.

---

## 🛠️ Tech Stack

- **Backend:** Python, Flask
- **AI Integration:** Google GenAI SDK / Vertex AI
- **Frontend:** Tailwind CSS, Chart.js, Vanilla JavaScript (PWA-ready)
- **Database & Hosting:** Google Cloud Firestore, Google Cloud Run, Artifact Registry

---

## 🚀 Local Development

1. Clone the repository:
   ```bash
   git clone [https://github.com/Suzuhisako/household-flask-app](https://github.com/YOUR_USERNAME/your-repo-name.git)
   cd your-repo-name

---

## 📄 License
This project is open-source and available under the MIT License.  
