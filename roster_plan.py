"""Set the daily plan of one ТП in the encrypted roster: python roster_plan.py "<surname name>" <plan>"""
import sys
import roster as R

q, plan = sys.argv[1], int(sys.argv[2])
parts = R.load()
tp = parts['tp']
k = R.key(q)
m = tp['key'] == k
if m.sum() != 1:
    print(f"::error::matches={int(m.sum())} for the given name (need exactly 1)")
    sys.exit(1)
old = int(tp.loc[m, 'plan'].iloc[0])
tp.loc[m, 'plan'] = plan
parts['tp'] = tp
R.save(parts)
print(f"::notice::roster plan changed {old} -> {plan} (1 person)")
