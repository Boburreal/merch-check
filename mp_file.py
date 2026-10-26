"""Monthly МП file in Bobur's "МП визит 01-DD.MM" format: К доктору, К контрагенту, Итог (+ Ежедневный, Визитлар тўлиқ,
Аптека муаммолари, Изоҳ). No plan for МП yet - facts only. Values only (no formulas)."""
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from tp_file import _hdr, BOX, GRN, YEL, RED

SHORT = {'gap': 'тез ёпилган', 'loc': 'локацияси ўзгарган аптека', 'photo': 'фото йўқ', 'same': 'фото1=фото2',
         'reuse': 'фото қайта ишлатилган', 'dup': 'такрорий визит', 'hours': 'иш вақтидан ташқари',
         'region_out': 'бошқа ҳудуддаги аптека', 'cluster': 'бир нуқтада 5+ аптека', 'multi': 'аптекага 3+ МП',
         'over7': 'бир аптекага 7+ визит'}


def _comment(g):
    parts = [f"{int(g['f_' + k].sum())} та {v}" for k, v in SHORT.items() if 'f_' + k in g and g['f_' + k].sum()]
    if g['Янги'].any():
        parts.insert(0, 'ЯНГИ МП')
    return "; ".join(parts)


def build(path, title, mp: pd.DataFrame, people: pd.DataFrame):
    mp = mp.copy()
    mp['Тип'] = mp['Тип визита'].map(lambda s: 'К доктору' if 'врач' in str(s).lower() else 'К контрагенту')
    order = list(people['name'])
    keymap = dict(zip(people['key'], people['name']))
    import roster as R
    mp['ФП'] = mp['МП'].map(lambda n: keymap.get(R.key(n), n))
    wb = Workbook()
    first = True
    for typ in ('К доктору', 'К контрагенту'):
        ws = wb.active if first else wb.create_sheet(typ)
        ws.title = typ; first = False
        cols = ['Дата', 'Тип', 'Объект', 'Фарм представитель', 'Регион', 'Ёпилган вақт', 'Изоҳ', 'Фото 1', 'Фото 2']
        _hdr(ws, 1, cols)
        x = mp[mp['Тип'] == typ].sort_values(['day', 'ФП', 'dt'])
        for i, r in enumerate(x.to_dict('records'), 2):
            vals = [r['Дата'], typ, r['Контр-агент/Врач'], r['ФП'], r['Иш ҳудуди'], r['Время завершения визита'],
                    r['Изоҳ'], r['Фото 1'], r['Фото 2']]
            for j, v in enumerate(vals, 1):
                c = ws.cell(i, j, v)
                if j in (8, 9) and isinstance(v, str) and v.startswith('http'):
                    c.hyperlink = v; c.value = 'Очиш'; c.font = Font(color='0563C1', underline='single')
            if r['Шубҳали']:
                ws.cell(i, 7).fill = YEL
        for j, w in enumerate([11, 14, 45, 34, 18, 16, 80, 8, 8], 1):
            ws.column_dimensions[get_column_letter(j)].width = w
        ws.freeze_panes = 'A2'; ws.auto_filter.ref = ws.dimensions

    # ---------- Итог (Bobur's layout) ----------
    ws = wb.create_sheet('Итог')
    names = order + [n for n in sorted(mp['ФП'].unique()) if n not in order]
    reg_of = dict(zip(people['name'], people['region']))
    reg_of.update(mp.groupby('ФП')['Иш ҳудуди'].first().to_dict())
    regions = list(dict.fromkeys([reg_of.get(n, '—') for n in names]))
    for c0, typ in ((1, 'К контрагенту'), (9, 'К доктору')):
        ws.cell(1, c0, typ).font = Font(bold=True); ws.cell(1, c0 + 4, typ).font = Font(bold=True)
        for j, h in enumerate(['ФП', 'Регион', 'Факт'], c0):
            x = ws.cell(2, j, h); x.font = Font(bold=True); x.fill = GRN; x.border = BOX
        for j, h in enumerate(['Регион', 'Кол-во', 'Уникальный'], c0 + 4):
            x = ws.cell(2, j, h); x.font = Font(bold=True); x.fill = GRN; x.border = BOX
        sub = mp[mp['Тип'] == typ]
        fact = sub.groupby('ФП').size()
        for i, n in enumerate(names, 3):
            for j, v in enumerate([n, reg_of.get(n, '—'), int(fact.get(n, 0))], c0):
                ws.cell(i, j, v).border = BOX
        ws.cell(len(names) + 3, c0 + 2, int(fact.sum())).font = Font(bold=True)
        # Уникальный = remove duplicates of Объект over the whole list (first occurrence), counted by employee region
        first_occ = sub.sort_values(['day', 'dt']).drop_duplicates('Контр-агент/Врач')
        uniq = first_occ['ФП'].map(reg_of).value_counts()
        kol = sub['ФП'].map(reg_of).value_counts()
        for i, rg in enumerate(regions, 3):
            for j, v in enumerate([rg, int(kol.get(rg, 0)), int(uniq.get(rg, 0))], c0 + 4):
                ws.cell(i, j, v).border = BOX
        rr = len(regions) + 3
        ws.cell(rr, c0 + 5, int(kol.sum())).font = Font(bold=True)
        ws.cell(rr, c0 + 6, int(uniq.sum())).font = Font(bold=True)
    for j, w in enumerate([34, 18, 8, 2, 18, 8, 11, 2, 34, 18, 8, 2, 18, 8, 11], 1):
        ws.column_dimensions[get_column_letter(j)].width = w

    # ---------- Ежедневный (facts per МП per day + comment) ----------
    ws = wb.create_sheet('Ежедневный')
    _hdr(ws, 1, ['Дата', '№', 'МП', 'Регион', 'К контрагенту', 'К доктору', 'Жами', 'Шубҳали', 'Комментария'])
    r = 2
    for day, g in mp.groupby('day', sort=True):
        tot = [0, 0, 0, 0]
        for n, (name, h) in enumerate(sorted(g.groupby('ФП'), key=lambda x: x[0].lower()), 1):
            a = int((h['Тип'] == 'К контрагенту').sum()); d = int((h['Тип'] == 'К доктору').sum()); s = int(h['Шубҳали'].sum())
            vals = [day.strftime('%d.%m'), n, name, h['Иш ҳудуди'].iloc[0], a, d, a + d, s, _comment(h)]
            for j, v in enumerate(vals, 1):
                ws.cell(r, j, v).border = BOX
            if vals[-1]:
                ws.cell(r, 9).fill = YEL
            tot = [tot[0] + a, tot[1] + d, tot[2] + a + d, tot[3] + s]; r += 1
        for j, v in enumerate([day.strftime('%d.%m'), None, 'ИТОГО', None] + tot + [None], 1):
            c = ws.cell(r, j, v); c.font = Font(bold=True); c.fill = GRN; c.border = BOX
        r += 1
    for j, w in enumerate([8, 5, 34, 18, 12, 10, 8, 9, 80], 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = 'A2'

    # ---------- Аптека муаммолари ----------
    ws = wb.create_sheet('Аптека муаммолари')
    _hdr(ws, 1, ['Объект', 'Муаммо', 'МП (лар)', 'Визитлар сони', 'Изоҳ'])
    rows = []
    for k, ttl, pat in [('region_out', 'Бошқа ҳудуддаги аптека', 'координатаси'), ('cluster', 'Бир нуқтада 5+ аптека', 'бир нуқтада'),
                        ('multi', '3+ МП борган', 'та МП борган'), ('over7', '7+ визит', 'марта визит'),
                        ('loc', 'Локацияси ўзгарган', 'локацияси ўзгартирилган')]:
        for obj, g in mp[mp['f_' + k]].groupby('Контр-агент/Врач'):
            note = g['Изоҳ'].str.split('; ').explode()
            note = note[note.str.contains(pat)]
            rows.append([obj, ttl, ", ".join(sorted(g['ФП'].unique())), len(g), note.iloc[0] if len(note) else ''])
    for i, row in enumerate(sorted(rows, key=lambda r: (r[1], -r[3])), 2):
        for j, v in enumerate(row, 1):
            ws.cell(i, j, v)
    for j, w in enumerate([45, 24, 50, 12, 90], 1):
        ws.column_dimensions[get_column_letter(j)].width = w

    ws = wb.create_sheet('Изоҳ')
    for t in [title, '', 'МП учун ҳозирча план йўқ — фақат факт.',
              'Итог: «Уникальный» — бутун рўйхат бўйича Объект такрорлари ўчирилган (биринчиси қолган), ходим ҳудуди бўйича саналган.',
              'Шубҳа белгилари ТП билан бир хил: тез ёпилган (≤1 дақ), фото, такрорий визит, иш вақтидан ташқари, локация ўзгариши,',
              '  аптека координатаси МП ҳудудидан ташқарида, бир нуқтада 5+ аптека, аптекага ойда 3+ МП, бир аптекага ойда 7+ визит.',
              'МП ҳудуди — рўйхатингиз бўйича; янги МП бўлса — у кўпроқ борган аптекалар ҳудуди бўйича олинади.']:
        ws.append([t])
    ws.column_dimensions['A'].width = 150
    wb.move_sheet('Итог', offset=-(len(wb.sheetnames) - 1))
    wb.active = 0
    wb.save(path)
