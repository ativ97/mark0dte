# 0DTE Quant Engine

A decision-support system for selling SPX 0DTE credit spreads. Combines real-time market data (Alpaca, Yahoo Finance, ThetaData) with regime classification, smart moat calculation, and position management.

**Current Version**: Phase 16 (V5.5+ with conditional expected move, reversal-aware exits, time-adjusted take profit)

## 1. Setup the Python Backend

```sh
cd backend

# Create a Conda environment
conda create -n mark python=3.13
conda activate mark

# Install dependencies
pip install -r requirements.txt
pip install pytest  # for running tests

# Run the server
python -m uvicorn main:app --reload
```

The server is now running on http://127.0.0.1:8000.

### Run Tests

```sh
cd backend
python -m pytest test_engine.py -v --tb=short
# Expected: 18 passed
```

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