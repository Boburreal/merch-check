"""Map any distributor's product name to Bobur's 14 products (exact spelling incl. trailing space)."""
import re

PRODUCTS = {
    'Риномакс Актив Таб №10': 21331.52,
    'Риномакс Хот Лимон 22г №15 ': 50394.624,
    'Риномакс Хот Эффект Лимон 22г №15': 50394.624,
    'Риномакс Хот.Экстра пор.22г.№15 Лимон': 50394.624,
    'Риноксил Формула + 0,05% спрей 10мл': 41163,
    'Риноксил Кидс 0,025% 10 мл спрей': 41474,
    'Риноксил Кидс капли 0.25%.10мл': 41473,
    'Риноксил Бэби 0,01% 10 мл капли': 41429,
    'Риноксил 0,1% 10мл спрей': 41173,
    'Форсил со вкусом апельсина 3г №30': 50064,
    'Мирамистин 50мл р-р': 66441,
    'Тивомакс-Дарница 42мг/мл 100мл': 37600,
    'Триомакс-Дарница 25мг/4мл №10': 111234,
    'Эрегра 100мг №4': 36064,
}
LAT = str.maketrans({'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х', 'k': 'к', 'm': 'м', 't': 'т', 'h': 'н', 'b': 'в', 'y': 'у'})


def norm(s) -> str:
    return re.sub(r'\s+', ' ', str(s).lower().translate(LAT)).strip()


def match(name) -> str | None:
    n = norm(name)
    if 'риномакс' in n or 'rinomaks' in n or 'риномак' in n:
        if 'актив' in n:
            return 'Риномакс Актив Таб №10'
        if 'хот' not in n and 'hot' not in n:
            return None
        if 'эффект' in n or 'эфект' in n or 'effekt' in n:
            return 'Риномакс Хот Эффект Лимон 22г №15'
        if 'экстра' in n or 'ekstra' in n or 'extra' in n:
            return 'Риномакс Хот.Экстра пор.22г.№15 Лимон'
        return 'Риномакс Хот Лимон 22г №15 '
    if 'риноксил' in n or 'rinoksil' in n:
        if 'формул' in n:
            return 'Риноксил Формула + 0,05% спрей 10мл'
        if 'бэби' in n or 'беби' in n or 'baby' in n or '0,01' in n or '0.01' in n:
            return 'Риноксил Бэби 0,01% 10 мл капли'
        if 'кидс' in n or 'kids' in n or '0,025' in n or '0.025' in n or '0,25' in n or '0.25' in n:
            return 'Риноксил Кидс капли 0.25%.10мл' if 'кап' in n else 'Риноксил Кидс 0,025% 10 мл спрей'
        if 'капл' in n:
            return None
        return 'Риноксил 0,1% 10мл спрей'
    if 'форсил' in n or 'forsil' in n:
        if '400' in n or 'light' in n or 'лайт' in n:
            return None                 # Форсил Light 400мг is not counted
        return 'Форсил со вкусом апельсина 3г №30'   # powder 3г №30 + Форсил экспресс 200мг (as in Bobur's file)
    if 'мирамистин' in n:
        return 'Мирамистин 50мл р-р' if '50' in n else None
    if 'тивомакс' in n:
        return 'Тивомакс-Дарница 42мг/мл 100мл'
    if 'триомакс' in n:
        return 'Триомакс-Дарница 25мг/4мл №10'
    if 'эрегра' in n:
        return 'Эрегра 100мг №4'
    return None
