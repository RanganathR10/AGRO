# SGB Agro Industries AI Sales Agent (fixed prototype)

## Run on Windows with VS Code
1. Extract this ZIP to a simple path such as `C:\sgb_ai_sales_agent_fixed`.
2. Open that folder in VS Code.
3. Open Terminal and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

If PowerShell blocks activation, use Command Prompt and run `.venv\Scripts\activate.bat`. Open `http://127.0.0.1:5000` while the terminal remains running.

## Import catalogue
Use `data/sgb_sample_product_catalogue.csv` and the Import CSV control in the right panel. Required headers are `sku,name,category,description`. Optional headers: `applications,limitations,price,currency,stock_status,specifications_json`. Import replaces the old catalogue atomically, so the old `REPLACE-WITH-OFFICIAL-PRODUCT` placeholder will disappear after a successful import. The UI shows an explicit error if the CSV is malformed.

## Test
- `What products do you sell?`
- `What are the prices?`
- `Recommend a product under ₹1000`
- `Show irrigation products`
- `Compare DEMO-IRR-001 and DEMO-SPR-002`
- `Is DEMO-MULCH-008 out of stock?`
- `What is the warranty period?`

## Important limitations
This is a local rule-based prototype, not a full conversational LLM. Recommendations use simple catalogue filters. Sample products and prices are fictional and are not verified SGB Agro Industries information. The mock-order panel is informational only; this build does not create real orders, collect payment, connect WhatsApp, or provide voice conversations. Do not use real customer personal information in demos.
