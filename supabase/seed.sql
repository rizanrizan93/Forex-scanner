-- Canonical reference symbols for the FX scanner universe.
insert into public.fx_symbols (symbol, base_currency, quote_currency, pip_size, tier)
values
  ('EURUSD','EUR','USD',0.0001,'A'),
  ('GBPUSD','GBP','USD',0.0001,'A'),
  ('USDJPY','USD','JPY',0.01,'A'),
  ('USDCHF','USD','CHF',0.0001,'A'),
  ('USDCAD','USD','CAD',0.0001,'A'),
  ('AUDUSD','AUD','USD',0.0001,'A'),
  ('NZDUSD','NZD','USD',0.0001,'A'),
  ('EURJPY','EUR','JPY',0.01,'B'),
  ('GBPJPY','GBP','JPY',0.01,'B'),
  ('EURGBP','EUR','GBP',0.0001,'B'),
  ('AUDJPY','AUD','JPY',0.01,'B'),
  ('CADJPY','CAD','JPY',0.01,'B'),
  ('EURCHF','EUR','CHF',0.0001,'B'),
  ('EURAUD','EUR','AUD',0.0001,'B'),
  ('GBPAUD','GBP','AUD',0.0001,'B')
on conflict (symbol) do update
set base_currency = excluded.base_currency,
    quote_currency = excluded.quote_currency,
    pip_size = excluded.pip_size,
    tier = excluded.tier;
