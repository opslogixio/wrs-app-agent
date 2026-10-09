/* Generate and download without navigating away from the report. */
(function () {
    document.querySelectorAll('form[data-pdf-export]').forEach(function (form) {
        if (form.dataset.exportBound) return;
        form.dataset.exportBound = 'true';
        form.addEventListener('submit', async function (event) {
            event.preventDefault();
            const button = form.querySelector('button[type="submit"]');
            const status = form.parentElement.querySelector('.pdf-export-status');
            function show(message) { if (status) status.textContent = message; }
            button.disabled = true;
            show('Generating PDF… You can continue viewing this report.');
            try {
                const response = await fetch(form.action, {
                    method: 'POST', body: new FormData(form), credentials: 'same-origin'
                });
                if (!response.ok || response.redirected) throw new Error('Unable to export this report. Please retry.');
                const job = await response.json();
                const deadline = Date.now() + 30 * 60 * 1000;
                let ready;
                while (Date.now() < deadline) {
                    const check = await fetch(job.status_url, {credentials: 'same-origin', cache: 'no-store'});
                    if (!check.ok || check.redirected) throw new Error('Unable to check this report. Please retry.');
                    const result = await check.json();
                    if (result.state === 'failed') throw new Error(result.error || 'Report generation failed.');
                    if (result.download_url) { ready = result.download_url; break; }
                    await new Promise(resolve => setTimeout(resolve, 3000));
                }
                if (!ready) throw new Error('The report is taking too long. Please retry.');
                const file = await fetch(ready, {credentials: 'same-origin', cache: 'no-store'});
                if (!file.ok || file.redirected) throw new Error('Unable to download this report. Please retry.');
                const url = URL.createObjectURL(await file.blob());
                const link = document.createElement('a');
                link.href = url;
                const filename = (file.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/);
                link.download = filename ? filename[1] : 'report.pdf';
                document.body.appendChild(link);
                link.click();
                link.remove();
                setTimeout(() => URL.revokeObjectURL(url), 60000);
                show('PDF downloaded.');
            } catch (error) {
                show(error.message || 'Unable to download this report. Please retry.');
            } finally {
                button.disabled = false;
            }
        });
    });
}());
