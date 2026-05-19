# 0DTE Quant System - Local Installation Guide

Follow these steps in your IDE terminal to spin up the dashboard.

## 1. Setup the Python Backend

Open your terminal in the backend directory and run:

```sh
cd backend

# Create a Conda environment (Recommended)
conda create -n 0dte_env python=3.9
conda activate 0dte_env

# Install the required Quantitative libraries
pip install -r requirements.txt

# Run the server
python main.py
```
*(Alternatively, you can run `main.py` directly using the green Play button in PyCharm, ensuring your Conda interpreter is selected).*

The server is now running on http://127.0.0.1:8000.

## 2. Setup the React Frontend

Open a new, second terminal tab so your backend keeps running:

```sh
cd frontend

# Install dependencies
npm install

# Install Tailwind CSS v4 and its Vite plugin
npm install @tailwindcss/vite@^4.3.0
```

### Configure Tailwind v4 with Vite:

Ensure your `frontend/vite.config.js` looks like this:

```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
})
```

Open `frontend/src/index.css` and ensure it only contains:

```css
@import "tailwindcss";
```

*(Note: Tailwind CSS v4 handles configuration natively via CSS, so `tailwind.config.js` and `postcss.config.js` are no longer needed).*

### Start the Dashboard:

```sh
npm run dev
```

Click the localhost link in your terminal to view your new Command Center.