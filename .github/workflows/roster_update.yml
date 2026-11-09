"""Apply a roster change from the GitHub secret ROSTER_UPDATE (names stay out of the public repo and logs).
Lines (tab or | separated):   NEW|Фамилия Имя|Регион   -> add to МП list
                              MOVE|Фамилия Имя|Регион  -> remove from ТП list, add to МП list (region from ТП row if known)
Only counts are printed."""
import os, sys
import pandas as pd
import roster as R

txt = os.environ.get("ROSTER_UPDATE", "").strip()
if not txt:
    print("::error::ROSTER_UPDATE secret is empty"); sys.exit(1)
parts = R.load()
tp, mp = parts['tp'].copy(), parts['mp'].copy()
for c in ('name', 'region', 'key'):
    if c not in mp:
        mp[c] = ''
added = moved = dup = missing = 0
for line in txt.splitlines():
    f = [x.strip() for x in line.replace('\t', '|').split('|')]
    if len(f) < 3 or f[0].upper() not in ('NEW', 'MOVE'):
        continue
    kind, name, region = f[0].upper(), f[1], f[2]
    k = R.key(name)
    if kind == 'MOVE':
        m = tp['key'] == k
        if m.any():
            region = str(tp.loc[m, 'region'].iloc[0]) or region
            tp = tp[~m]
            moved += 1
        else:
            missing += 1                         # not in the ТП list (already moved or spelled differently)
    if (mp['key'] == k).any():
        dup += 1
        continue
    mp = pd.concat([mp, pd.DataFrame([{'name': name, 'region': region, 'key': k}])], ignore_index=True)
    added += 1
parts['tp'], parts['mp'] = tp, mp
R.save(parts)
print(f"::notice::roster updated: added to МП {added}, removed from ТП {moved}, already in МП {dup}, not found in ТП {missing}; "
      f"now ТП={len(tp)} МП={len(mp)}")
