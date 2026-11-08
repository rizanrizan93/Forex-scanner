using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Internals;

namespace Rizan.Research.Btc2325;

// RESEARCH-ONLY cTrader signal and virtual-fill engine. There is deliberately no
// ExecuteMarketOrder, PendingOrders.Add, ModifyPosition or ClosePosition call.
// This does not alter any BUY050 / XAU / EUR / incumbent BTC strategy state.
[Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
public sealed class RizanBtc2325Shadow : Robot
{
    private const string CandidateId = "RIZAN_BTC_SWEEP20_EMA20_GUARD10_2332M_RESEARCH_FROZEN_20261108";
    private const double RiskFraction = 0.025;
    private const double MarginFraction = 0.10;
    private const double ModelLeverage = 200.0;
    private const double SpreadFractionTotal = 0.0005;
    private const double SlipFractionPerLeg = 0.0001;
    private const double CommissionPerSide = 0.0005;
    private const double FundingPerDay = 0.0003;
    private const double MaxModelBtcQuantity = 3200;
    private const double MinModelBtcQuantity = 0.01;
    private const double BtcStep = 0.01;

    [Parameter("Simulated cost multiplier", DefaultValue = 1, MinValue = 1, MaxValue = 2, Step = 1, Group = "Research")]
    public int CostMultiplier { get; set; } = 1;

    [Parameter("Show skipped signals", DefaultValue = true, Group = "Research")]
    public bool LogSkippedSignals { get; set; } = true;

    private Bars _h1 = null!;
    private Bars _h4 = null!;
    private Bars _m1 = null!;
    private DateTime _lastDecisionHourUtc;
    private DateTime _lastClosedMinuteUtc;
    private DateTime _nextStatusUtc;
    private DateTime _lastExitUtc;
    private VirtualBasket? _basket;
    private double _cash, _closedPeak;
    private int _signals, _paperTrades, _wins, _skipped;

    private sealed class VirtualBasket
    {
        public required string Family { get; init; }
        public required int Side { get; init; }
        public required DateTime EntryAtUtc { get; init; }
        public required DateTime ExpiresUtc { get; init; }
        public required double Quantity { get; init; }
        public required double Entry { get; init; }
        public required double Stop { get; init; }
        public required double Target { get; init; }
    }

    private readonly record struct Signal(int Side, string Family, double Distance, int HoldHours);

    protected override void OnStart()
    {
        _cash = Account.Balance;
        _closedPeak = _cash;
        _h1 = MarketData.GetBars(TimeFrame.Hour, "BTCUSD");
        _h4 = MarketData.GetBars(TimeFrame.Hour4, "BTCUSD");
        _m1 = MarketData.GetBars(TimeFrame.Minute, "BTCUSD");
        _lastDecisionHourUtc = DateTime.MinValue;
        _lastClosedMinuteUtc = DateTime.MinValue;
        Print("BTC2325_RESEARCH_ONLY id={0}; orders_enabled=False; signal=H4_SWEEP20_THEN_H1_EMA20; account_scope=NO_POSITION_MODIFICATION", CandidateId);
        Print("BTC2325_PARITY_WARNING frozen_guard=historical_BUY050_closed_balance; runtime_guard=causal_observed_account_balance; model_not_equivalent=True");
        Print("BTC2325_PARITY_WARNING native_shared_account_replay=False; floating_DD_unverified=True; max_3200BTC_not_broker_verified=True");
        Timer.Start(TimeSpan.FromSeconds(1));
    }

    private static double EmaAt(Bars bars, int index, int period)
    {
        if(index < 0) return double.NaN;
        double v = bars.ClosePrices[0], a = 2.0 / (period + 1.0);
        for(int i = 1; i <= index; ++i) v += a * (bars.ClosePrices[i] - v);
        return v;
    }

    private static double AtrAt(Bars bars, int index)
    {
        if(index < 0) return double.NaN;
        double atr = bars.HighPrices[0] - bars.LowPrices[0];
        for(int i = 1; i <= index; ++i)
        {
            double h = bars.HighPrices[i], l = bars.LowPrices[i], pc = bars.ClosePrices[i-1];
            double tr = Math.Max(h-l, Math.Max(Math.Abs(h-pc), Math.Abs(l-pc)));
            atr += (tr - atr) / 14.0;
        }
        return atr;
    }

    private static double RsiAt(Bars bars, int index)
    {
        if(index < 2) return double.NaN;
        double d = bars.ClosePrices[1] - bars.ClosePrices[0];
        double gain = Math.Max(d, 0), loss = Math.Max(-d, 0);
        for(int i = 2; i <= index; ++i)
        {
            d = bars.ClosePrices[i] - bars.ClosePrices[i-1];
            gain += (Math.Max(d, 0) - gain) / 14;
            loss += (Math.Max(-d, 0) - loss) / 14;
        }
        return 100.0 - 100.0 / (1.0 + gain / Math.Max(loss, 1e-8));
    }

    private static double EfficiencyAt(Bars bars, int index)
    {
        if(index < 20) return double.NaN;
        double cumulative = 0;
        for(int i = index-19; i <= index; ++i)
            cumulative += Math.Abs(bars.ClosePrices[i] - bars.ClosePrices[i-1]);
        return Math.Abs(bars.ClosePrices[index] - bars.ClosePrices[index-20]) / Math.Max(cumulative, 1e-8);
    }

    private static int LastClosed(Bars bars, DateTime endUtc, int periodHours)
    {
        for(int i = bars.Count-1; i >= 0; --i)
            if(bars.OpenTimes[i].AddHours(periodHours) <= endUtc)
                return i;
        return -1;
    }

    private Signal? ClosedSignal(DateTime decisionUtc)
    {
        // The H1 signal is from the hour which just closed; H4 features are the
        // most recent *completed* H4 candle, never the H4 in progress.
        int hi = LastClosed(_h1, decisionUtc, 1), h4i = LastClosed(_h4, decisionUtc, 4);
        if(hi < 210 || h4i < 100) return null;
        double atr4 = AtrAt(_h4, h4i), atr1 = AtrAt(_h1, hi);
        if(!double.IsFinite(atr4) || !double.IsFinite(atr1) || atr4 <= 0 || atr1 <= 0) return null;
        double o4 = _h4.OpenPrices[h4i], c4 = _h4.ClosePrices[h4i], high4 = _h4.HighPrices[h4i], low4 = _h4.LowPrices[h4i];
        double ema4Fast = EmaAt(_h4, h4i, 20), ema4Slow = EmaAt(_h4, h4i, 80);
        double ema1 = EmaAt(_h1, hi, 20), er4 = EfficiencyAt(_h4, h4i), rsi4 = RsiAt(_h4, h4i);
        double o1 = _h1.OpenPrices[hi], c1 = _h1.ClosePrices[hi], high1 = _h1.HighPrices[hi], low1 = _h1.LowPrices[hi];

        // Frozen priority: H4 sweep is evaluated only on H4 closing boundaries.
        if(decisionUtc.Hour % 4 == 0 && _h4.OpenTimes[h4i].AddHours(4) == decisionUtc && h4i >= 20)
        {
            double priorHi = double.MinValue, priorLo = double.MaxValue;
            for(int i = h4i-20; i < h4i; i++)
            {
                priorHi = Math.Max(priorHi, _h4.HighPrices[i]);
                priorLo = Math.Min(priorLo, _h4.LowPrices[i]);
            }
            // Strict comparisons deliberately match research.py signal_sweep(20,.05,'neutral').
            if(low4 < priorLo - .05 * atr4 && c4 > priorLo + .05 * atr4 && c4 > o4 && rsi4 < 70)
                return new Signal(+1, "H4_SWEEP20", 1.5*atr4, 72);
            if(high4 > priorHi + .05 * atr4 && c4 < priorHi - .05 * atr4 && c4 < o4 && rsi4 > 30)
                return new Signal(-1, "H4_SWEEP20", 1.5*atr4, 72);
        }
        // Same H4 trend/ER and H1 depth=0, body=.25 conditions as research.py.
        if(ema4Fast > ema4Slow && c4 > ema4Slow && low1 <= ema4Fast && c1 > ema4Fast && c1 > o1 && c1 > ema1 && c1-o1 > .25*atr1 && er4 > .15)
            return new Signal(+1, "H1_EMA20", 2*atr1, 128);
        if(ema4Fast < ema4Slow && c4 < ema4Slow && high1 >= ema4Fast && c1 < ema4Fast && c1 < o1 && c1 < ema1 && o1-c1 > .25*atr1 && er4 > .15)
            return new Signal(-1, "H1_EMA20", 2*atr1, 128);
        return null;
    }

    private static bool EntrySession(DateTime utc) =>
        utc.DayOfWeek != DayOfWeek.Saturday && utc.DayOfWeek != DayOfWeek.Sunday &&
        !(utc.DayOfWeek == DayOfWeek.Friday && utc.Hour >= 22);

    private static bool ExitWeekend(DateTime utc) =>
        utc.DayOfWeek == DayOfWeek.Saturday || utc.DayOfWeek == DayOfWeek.Sunday ||
        (utc.DayOfWeek == DayOfWeek.Friday && utc.Hour >= 22);

    private bool IncumbentBusy() => Positions.Any(p => p.SymbolName == "BTCUSD") ||
                                    PendingOrders.Any(p => p.SymbolName == "BTCUSD");

    private bool CausalObservedGuardOk()
    {
        // This guard is intentionally NOT passed off as the fixed BUY050 baseline
        // historical cash curve, whose future path cannot be used for live signals.
        _closedPeak = Math.Max(_closedPeak, Account.Balance);
        return _closedPeak > 0 && (1-Account.Balance/_closedPeak) < .10;
    }

    private void Decide(DateTime hourUtc, DateTime nowUtc)
    {
        if(_lastDecisionHourUtc == hourUtc) return;
        _lastDecisionHourUtc = hourUtc;
        var signal = ClosedSignal(hourUtc);
        if(signal == null) return;
        ++_signals;
        string reason = "";
        if(_basket != null) reason = "EXTRA_BASKET_ACTIVE";
        else if(!EntrySession(hourUtc)) reason = "WEEKEND_ENTRY_LOCK";
        else if(IncumbentBusy()) reason = "BTC_INCUMBENT_PRIORITY_OR_BROKER_EXPOSURE";
        else if(!CausalObservedGuardOk()) reason = "CAUSAL_BALANCE_GUARD_10PCT";
        else if(nowUtc - hourUtc > TimeSpan.FromMinutes(2)) reason = "MISSED_NEXT_H1_OPEN";
        else if(_lastExitUtc != default && hourUtc < _lastExitUtc.AddHours(6)) reason = "SIX_HOUR_COOLDOWN";

        if(reason != "")
        {
            ++_skipped;
            if(LogSkippedSignals) Print("BTC2325_SHADOW_SKIP at={0:o}; family={1}; side={2}; reason={3}",hourUtc,signal.Value.Family,signal.Value.Side,reason);
            return;
        }
        int currentH1 = _h1.Count-1;
        if(currentH1<0 || _h1.OpenTimes[currentH1] != hourUtc)
        {
            ++_skipped;
            Print("BTC2325_SHADOW_SKIP reason=NEW_H1_BAR_UNAVAILABLE; at={0:o}",hourUtc);
            return;
        }
        var s = signal.Value;
        double rawOpen = _h1.OpenPrices[currentH1];
        double assumedEntry = rawOpen * (1+s.Side*(SpreadFractionTotal/2 + SlipFractionPerLeg*CostMultiplier));
        double riskPerBtc = s.Distance + assumedEntry*(.0005 + .0012*CostMultiplier);
        double qty = Math.Floor(Math.Min(MaxModelBtcQuantity,
                         Math.Min(_cash*RiskFraction/riskPerBtc,_cash*MarginFraction*ModelLeverage/assumedEntry)) / BtcStep) * BtcStep;
        if(!double.IsFinite(qty) || qty<MinModelBtcQuantity)
        {
            ++_skipped;
            Print("BTC2325_SHADOW_SKIP reason=MODEL_QUANTITY_BELOW_MIN; cash={0:F2}",_cash);
            return;
        }
        _basket=new VirtualBasket{
            Family=s.Family,Side=s.Side,EntryAtUtc=hourUtc,ExpiresUtc=hourUtc.AddHours(s.HoldHours),
            Quantity=qty,Entry=assumedEntry,Stop=assumedEntry-s.Side*s.Distance,
            Target=assumedEntry+s.Side*s.Distance*10
        };
        ++_paperTrades;
        Print("BTC2325_PAPER_ENTRY at={0:o}; side={1}; family={2}; qty_model_btc={3:F2}; entry={4:F2}; sl={5:F2}; tp={6:F2}; LIVE_ORDER_SENT=False",
            hourUtc,s.Side>0?"BUY":"SELL",s.Family,qty,assumedEntry,_basket.Stop,_basket.Target);
    }

    private void ExitVirtual(DateTime minuteUtc, double price, string reason)
    {
        if(_basket == null)return;
        var b=_basket;
        double modelExit = reason == "SL_INTRABAR" ? b.Stop*(1-b.Side*SlipFractionPerLeg*CostMultiplier) :
                           reason == "TP_INTRABAR" ? b.Target :
                           price*(1-b.Side*(SpreadFractionTotal/2+SlipFractionPerLeg*CostMultiplier));
        double holdingDays=Math.Max(1,(minuteUtc-b.EntryAtUtc).TotalMinutes+1)/1440;
        double fees=b.Quantity*CommissionPerSide*CostMultiplier*(b.Entry+modelExit);
        double funding=b.Quantity*b.Entry*FundingPerDay*holdingDays*CostMultiplier;
        double pnl=b.Side*b.Quantity*(modelExit-b.Entry)-fees-funding;
        _cash+=pnl;
        _closedPeak=Math.Max(_closedPeak,_cash);
        if(pnl>0)++_wins;
        _basket=null;
        _lastExitUtc=minuteUtc;
        Print("BTC2325_PAPER_EXIT at={0:o}; family={1}; reason={2}; pnl_model_usd={3:F2}; cash_model={4:F2}; LIVE_ORDER_SENT=False",
            minuteUtc,b.Family,reason,pnl,_cash);
    }

    private void MonitorVirtual(DateTime nowUtc)
    {
        if(_basket == null)return;
        // Process all completed minutes since last timer (including cTrader tab inactivity).
        for(int i=0;i<_m1.Count;i++)
        {
            var at=_m1.OpenTimes[i];
            if(at<=_lastClosedMinuteUtc || at.AddMinutes(1)>nowUtc)continue;
            _lastClosedMinuteUtc=at;
            var b=_basket;
            if(b==null)break;
            if(at<b.EntryAtUtc)continue;
            if(IncumbentBusy()) {ExitVirtual(at,_m1.OpenPrices[i],"INCUMBENT_PRIORITY");break;}
            if(ExitWeekend(at)) {ExitVirtual(at,_m1.OpenPrices[i],"FRIDAY_WEEKEND_FLAT");break;}
            double o=_m1.OpenPrices[i], h=_m1.HighPrices[i], l=_m1.LowPrices[i], c=_m1.ClosePrices[i];
            if(b.Side*(o-b.Stop)<=0) {ExitVirtual(at,o,"SL_GAP_OPEN");break;}
            if((b.Side>0 && l<=b.Stop)||(b.Side<0 && h>=b.Stop)) {ExitVirtual(at,b.Stop,"SL_INTRABAR");break;}
            if((b.Side>0 && h>=b.Target)||(b.Side<0 && l<=b.Target)) {ExitVirtual(at,b.Target,"TP_INTRABAR");break;}
            if(at>=b.ExpiresUtc) {ExitVirtual(at,c,"MAX_HOLD");break;}
        }
    }

    protected override void OnTimer()
    {
        try
        {
            DateTime now=Server.TimeInUtc;
            if(_basket != null) MonitorVirtual(now);
            else if(_m1.Count>0) _lastClosedMinuteUtc=_m1.OpenTimes[Math.Max(0,_m1.Count-2)];
            var hour=new DateTime(now.Year,now.Month,now.Day,now.Hour,0,0,DateTimeKind.Utc);
            Decide(hour,now);
            if(now>=_nextStatusUtc)
            {
                _nextStatusUtc=now.AddMinutes(1);
                Print("BTC2325_SHADOW_HEALTH at={0:o}; basket={1}; paper_cash={2:F2}; signals={3}; paper_trades={4}; wins={5}; skipped={6}; live_orders=0; data_source=cTrader_broker_not_Bitstamp",
                    now,_basket!=null,_cash,_signals,_paperTrades,_wins,_skipped);
            }
        }
        catch(Exception e)
        {
            // On unexpected data fault stop the simulation. No live positions are affected.
            Print("BTC2325_SHADOW_FAULT type={0}; simulation_stopped=True",e.GetType().Name);
            Stop();
        }
    }

    protected override void OnStop() => Print("BTC2325_SHADOW_STOP; live_orders_sent=0");
}