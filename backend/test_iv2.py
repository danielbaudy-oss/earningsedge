from app.ingestion.options_iv import get_expected_move

for ticker in ["NVDA", "AAPL", "HD", "COST", "AMD"]:
    result = get_expected_move(ticker)
    if result.get("available"):
        print(f"{ticker}: Expected move ±{result['expected_move_pct']}%, "
              f"IV {result['atm_iv']}%, Price ${result['current_price']}")
    else:
        print(f"{ticker}: not available - {result.get('error', 'unknown')}")
