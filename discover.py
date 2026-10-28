import store
lg = store.load('loc_log')
n = lg.groupby('Аниқланди')['Ўзгариш'].transform('size')
bad = (n > 300) & lg['Ўзгариш'].isin(['Аптека базадан ўчирилди', 'Янги аптека қўшилди'])
store.save('loc_log', lg[~bad])
print(f"::notice::removed {int(bad.sum())} glitch add/delete rows, kept {int((~bad).sum())}")
