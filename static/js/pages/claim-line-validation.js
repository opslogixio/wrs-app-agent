/* Validate each claim line without submitting or clearing entered values. */
document.addEventListener('DOMContentLoaded', function () {
    const completionStatuses = ['pending', 'requires attention'];
    const commentStatuses = ['requires attention', 'not submitted', 'rejected'];
    document.querySelectorAll('.line-update-form, .claim-line-form').forEach(function (form) {
        const status = form.elements.namedItem('claim_status');
        const completion = form.elements.namedItem('start_date');
        const comment = form.elements.namedItem('comment');
        function updateRequirements() {
            const option = status && status.options[status.selectedIndex];
            const name = option ? (option.dataset.statusName || option.textContent).trim().toLowerCase() : '';
            if (completion && completion.type !== 'hidden') {
                completion.required = completionStatuses.includes(name);
                completion.setCustomValidity(completion.required && !completion.value.trim()
                    ? 'Completion Date is required for Pending and Requires Attention claims.' : '');
                completion.setAttribute('aria-required', String(completion.required));
            }
            if (comment && status) {
                comment.required = status.value !== status.dataset.originalStatus &&
                    (commentStatuses.includes(name) || option.dataset.commentRequired === 'true');
                comment.setCustomValidity(comment.required && !comment.value.trim()
                    ? 'A comment is required for this status change.' : '');
                const notice = form.querySelector('.comment-requirement');
                if (notice) notice.classList.toggle('d-none', !comment.required);
            }
        }
        updateRequirements();
        if (status) status.addEventListener('change', updateRequirements);
        if (completion) {
            completion.addEventListener('input', updateRequirements);
            completion.addEventListener('change', updateRequirements);
            // Bootstrap datepicker emits a jQuery event when a date is picked.
            if (window.jQuery) window.jQuery(form).on('changeDate', updateRequirements);
        }
        if (comment) comment.addEventListener('input', updateRequirements);
        form.addEventListener('submit', function (event) {
            updateRequirements();
            if (!form.reportValidity()) event.preventDefault();
        });
    });
});
