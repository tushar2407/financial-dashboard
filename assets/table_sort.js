document.addEventListener('click', function (e) {
    if (!e.target.matches('.glass-table thead th')) return;

    const th = e.target;
    const table = th.closest('table');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const index = Array.from(th.parentNode.children).indexOf(th);
    const ascending = th.dataset.order !== 'asc';

    // Clear other headers' state
    Array.from(th.parentNode.children).forEach(header => {
        if (header !== th) delete header.dataset.order;
    });

    // Sort rows
    rows.sort((a, b) => {
        const aVal = a.children[index].innerText.replace(/[$,%]/g, '').trim();
        const bVal = b.children[index].innerText.replace(/[$,%]/g, '').trim();

        const aNum = parseFloat(aVal);
        const bNum = parseFloat(bVal);

        if (!isNaN(aNum) && !isNaN(bNum)) {
            return ascending ? aNum - bNum : bNum - aNum;
        }

        return ascending ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    });

    // Update data attribute for next click
    th.dataset.order = ascending ? 'asc' : 'desc';

    // Highlight current sort
    Array.from(th.parentNode.children).forEach(header => header.style.color = 'rgba(255, 255, 255, 0.5)');
    th.style.color = '#fff';

    // Append sorted rows
    rows.forEach(row => tbody.appendChild(row));
});
