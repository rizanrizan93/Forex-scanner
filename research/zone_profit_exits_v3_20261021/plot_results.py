import json
import numpy as np,pandas as pd
import matplotlib.pyplot as plt
from profit_engine import ROOT

def main():
    s=pd.read_csv(ROOT/'COMPARISON.csv');cfg=json.loads((ROOT/'LOCKED_PROTOCOL_V3.json').read_text());selected=json.loads((ROOT/'LOCKED_TRAIN_SELECTION.json').read_text())['policy']
    policies=[x['id'] for x in cfg['exit_variants']]
    labels=['TP1R /60m','TP1.5R /60m','TP2R /120m','Structural cap2R','Partial1R→2R','BE after1R','Trail0.75R','Protect at30m']
    x=s[(s.split=='new_validation')&s.scope.eq('one_position')]
    fig,(ax,bx)=plt.subplots(1,2,figsize=(14,5.7))
    for k,c in enumerate([1,1.5,2]):
        y=[x[(x.policy==p)&(x.cost_multiple==c)].sum_net_R.iloc[0] for p in policies]
        ax.bar(np.arange(len(policies))+(k-1)*.24,y,width=.24,label=f'Cost {c:g}×',color=['#2a8d82','#6388ab','#c77671'][k])
    ax.set_xticks(np.arange(8),labels,rotation=42,ha='right');ax.set_ylabel('Cumulative net R (one position per policy)');ax.legend(fontsize=8)
    a=pd.read_csv(ROOT/'MATCHED_ENTRY_EXIT_ABLATION.csv');a=a[(a.split=='new_validation')&(a.cost_multiple==1)]
    vals=[a[a.policy.eq(p)].mean_exit_delta_R.iloc[0] for p in policies]
    bx.bar(np.arange(8),vals,color=['#349789' if v>=0 else '#bb6465' for v in vals]);bx.set_xticks(np.arange(8),labels,rotation=42,ha='right')
    bx.set_ylabel('Mean net R improvement vs TP1R on identical entries')
    for a in (ax,bx):a.axhline(0,c='#555',lw=.8);a.spines[['top','right']].set_visible(False)
    fig.suptitle('Profit exit V3 | NEW dates only:1Jul,1Aug,1Oct,1Nov2024 | Bybit BTCUSDT',fontsize=12)
    fig.text(.02,.025,'Selected BEFORE new-date outcomes: '+selected+' | Unit-R research; no account-return or XAU/EUR claim.',fontsize=9)
    fig.tight_layout(rect=[0,.08,1,.93]);fig.savefig(ROOT/'NEW_VALIDATION_PROFIT.png',dpi=150);plt.close(fig)

if __name__=='__main__':main()
