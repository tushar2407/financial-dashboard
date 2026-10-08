// Click a column header in a .data-table to sort its rows; click again to reverse.
// Shift+click adds the column as the next sort level (or reverses it if already
// a level), so ties in the first column are ordered by the second, and so on.
// Arrows (and level numbers when sorting by several columns) are drawn by CSS
// from th[data-order] / th[data-rank]. Footer rows stay put.
(function () {
    const DASH = '—';

    function sortKey(cell) {
        // Two-line cells sort by their first line (e.g. price above its date)
        const text = cell.innerText.split('\n')[0].trim();
        if (text === '' || text === DASH) return { empty: true };
        const numeric = text.replace(/−/g, '-').replace(/[$,%+<]/g, '').trim();
        if (/^-?\d+(\.\d+)?$/.test(numeric)) return { num: parseFloat(numeric) };
        const withUnit = numeric.match(/^(-?\d+(\.\d+)?) (days?|shares)$/);   // "142 days"
        if (withUnit) return { num: parseFloat(withUnit[1]) };
        const when = Date.parse(text);
        if (!isNaN(when) && /\d{4}/.test(text)) return { num: when };
        return { str: text.toLowerCase() };
    }

    function compare(a, b) {
        if (a.num !== undefined && b.num !== undefined) return a.num - b.num;
        return String(a.str ?? a.num).localeCompare(String(b.str ?? b.num));
    }

    // One sort level: blanks always last, otherwise in the level's direction
    function compareLevel(a, b, order) {
        if (a.empty || b.empty) return a.empty === b.empty ? 0 : (a.empty ? 1 : -1);
        return order === 'asc' ? compare(a, b) : compare(b, a);
    }

    function defaultOrder(tbody, index) {
        // Numbers default to largest first; text to A-Z
        const first = Array.from(tbody.rows).map(r => sortKey(r.children[index])).find(k => !k.empty) || {};
        return first.num !== undefined ? 'desc' : 'asc';
    }

    // Current sort levels, read from the header cells: [{th, index, order}] by rank
    function readLevels(headers) {
        return headers
            .filter(h => h.dataset.order)
            .map(h => ({ th: h, index: headers.indexOf(h), order: h.dataset.order,
                         rank: Number(h.dataset.rank || 1) }))
            .sort((a, b) => a.rank - b.rank);
    }

    function nextLevels(levels, th, index, tbody, additive) {
        const existing = levels.find(l => l.th === th);
        const flip = order => (order === 'asc' ? 'desc' : 'asc');
        if (additive) {
            return existing
                ? levels.map(l => (l.th === th ? { ...l, order: flip(l.order) } : l))
                : [...levels, { th, index, order: defaultOrder(tbody, index) }];
        }
        // Plain click: sort by this column only (reverse if it already was the only one)
        const order = existing && levels.length === 1 ? flip(existing.order) : defaultOrder(tbody, index);
        return [{ th, index, order }];
    }

    function paintHeaders(headers, levels) {
        headers.forEach(h => { delete h.dataset.order; delete h.dataset.rank; });
        levels.forEach((l, i) => {
            l.th.dataset.order = l.order;
            if (levels.length > 1) l.th.dataset.rank = String(i + 1);
        });
    }

    document.addEventListener('click', function (e) {
        const th = e.target.closest('.data-table thead th');
        if (!th) return;
        const tbody = th.closest('table').querySelector('tbody');
        if (!tbody) return;
        const headers = Array.from(th.parentNode.children);
        const index = headers.indexOf(th);

        const levels = nextLevels(readLevels(headers), th, index, tbody, e.shiftKey);
        paintHeaders(headers, levels);

        const rows = Array.from(tbody.rows).map(row => ({
            row, keys: levels.map(l => sortKey(row.children[l.index])),
        }));
        rows.sort((a, b) => {
            for (let i = 0; i < levels.length; i++) {
                const c = compareLevel(a.keys[i], b.keys[i], levels[i].order);
                if (c !== 0) return c;
            }
            return 0;
        });
        rows.forEach(r => tbody.appendChild(r.row));
    });
})();
