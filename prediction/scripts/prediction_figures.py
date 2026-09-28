"""Reliability diagram + bootstrap CIs for the match-outcome model."""
import argparse, numpy as np, pandas as pd
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LAB = {"H":0,"D":1,"A":2}

def load(csv):
    df = pd.read_csv(csv)
    return df[["p_home","p_draw","p_away"]].to_numpy(), df["actual"].map(LAB).to_numpy()

def brier(P, y):
    oh = np.zeros_like(P); oh[np.arange(len(y)), y] = 1
    return float(np.mean((P-oh)**2))

def acc(P, y):
    return float((P.argmax(1)==y).mean())

def bootstrap(P, y, n_boot=2000, seed=0):
    rng = np.random.default_rng(seed); n=len(y); a=[]; b=[]
    for _ in range(n_boot):
        idx = rng.integers(0,n,n)
        a.append(acc(P[idx],y[idx])); b.append(brier(P[idx],y[idx]))
    ci = lambda v:(np.percentile(v,2.5),np.percentile(v,97.5))
    return (acc(P,y),)+ci(a), (brier(P,y),)+ci(b)

def reliability(P, y, bins=10):
    conf=P.max(1); pred=P.argmax(1); correct=(pred==y).astype(float)
    edges=np.linspace(0,1,bins+1); xs=[]; ys=[]; ns=[]; ece=0.0
    for i in range(bins):
        m=(conf>=edges[i])&(conf<edges[i+1] if i<bins-1 else conf<=edges[i+1])
        if m.sum()==0: continue
        xs.append(conf[m].mean()); ys.append(correct[m].mean()); ns.append(int(m.sum()))
        ece+=(m.sum()/len(y))*abs(correct[m].mean()-conf[m].mean())
    return np.array(xs),np.array(ys),ns,ece

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--csv",default="backtest_results/backtest_no_odds.csv")
    ap.add_argument("--out",default="backtest_results/reliability.pdf")
    a=ap.parse_args()
    P,y=load(a.csv)
    (ac,al,ah),(br,bl,bh)=bootstrap(P,y)
    print(f"n = {len(y)}")
    print(f"accuracy = {ac:.3f}  95% CI [{al:.3f}, {ah:.3f}]")
    print(f"brier    = {br:.3f}  95% CI [{bl:.3f}, {bh:.3f}]")
    xs,ys,ns,ece=reliability(P,y)
    print(f"ECE = {ece:.3f}")
    fig,ax=plt.subplots(figsize=(4.2,4.2))
    ax.plot([0,1],[0,1],"--",color="#888",lw=1,label="perfect calibration")
    ax.plot(xs,ys,"o-",color="#1F3864",lw=1.6,label="model")
    ax.set_xlabel("predicted confidence"); ax.set_ylabel("observed accuracy")
    ax.set_xlim(0,1); ax.set_ylim(0,1); ax.set_aspect("equal")
    ax.set_title(f"Reliability (ECE={ece:.3f})",fontsize=10)
    ax.legend(fontsize=8,loc="upper left"); fig.tight_layout()
    Path(a.out).parent.mkdir(exist_ok=True,parents=True)
    fig.savefig(a.out); fig.savefig(a.out.replace(".pdf",".png"),dpi=150)
    print("figure ->",a.out)

if __name__=="__main__": main()
