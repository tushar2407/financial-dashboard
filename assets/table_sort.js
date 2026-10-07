// Click a column header in a .data-table to sort its rows; click again to reverse.
// The arrow is drawn by CSS from th[data-order]. Footer rows stay put.
(function () {
    const DASH = '—';

    function sortKey(cell) {
        // Two-line cells sort by their first line (e.g. price above its date)
        const text = cell.innerText.split('\n')[0].trim();
        if (text === '' || text === DASH) return { empty: true };
        const numeric = text.replace(/−/g, '-').replace(/[$,%+<]/g, '').trim();
        if (/^-?\d+(\.\d+)?$/.test(numeric)) return { num: parseFloat(numeric) };
        const when = Date.parse(text);
        if (!isNaN(when) && /\d{4}/.test(text)) return { num: when };
        return { str: text.toLowerCase() };
    }

    function compare(a, b) {
        if (a.empty || b.empty) return a.empty === b.empty ? 0 : (a.empty ? 1 : -1);
        if (a.num !== undefined && b.num !== undefined) return a.num - b.num;
        return String(a.str ?? a.num).localeCompare(String(b.str ?? b.num));
    }

    document.addEventListener('click', function (e) {
        const th = e.target.closest('.data-table thead th');
        if (!th) return;
        const tbody = th.closest('table').querySelector('tbody');
        if (!tbody) return;
        const index = Array.from(th.parentNode.children).indexOf(th);
        // Numbers default to largest first; text to A-Z
        const firstKey = tbody.rows[0] ? sortKey(tbody.rows[0].children[index]) : {};
        const startDesc = firstKey.num !== undefined;
        const order = th.dataset.order ? (th.dataset.order === 'asc' ? 'desc' : 'asc')
                                       : (startDesc ? 'desc' : 'asc');

        Array.from(th.parentNode.children).forEach(h => { if (h !== th) delete h.dataset.order; });
        th.dataset.order = order;

        const rows = Array.from(tbody.rows).map(row => ({ row, key: sortKey(row.children[index]) }));
        rows.sort((a, b) => {
            if (a.key.empty || b.key.empty) return compare(a.key, b.key);  // blanks always last
            return order === 'asc' ? compare(a.key, b.key) : compare(b.key, a.key);
        });
        rows.forEach(r => tbody.appendChild(r.row));
    });
})();
