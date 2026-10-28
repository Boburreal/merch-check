import store
lg = store.load('loc_log')
vc = lg.groupby('Аниқланди')['Ўзгариш'].value_counts().unstack(fill_value=0)
vc['n'] = vc.sum(axis=1)
print("::notice::stamps=" + str(len(vc)) + " big: " + vc[vc.n > 300].to_string().replace('\n', ' | ')[:2500])
print("::notice::small total=" + str(int(vc[vc.n <= 300].n.sum())))
