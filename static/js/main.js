document.addEventListener('DOMContentLoaded', () => {
    const timestampElement = document.querySelector('[data-current-year]');
    if (timestampElement) {
        timestampElement.textContent = new Date().getFullYear();
    }

    if (window.bootstrap) {
        const tooltipTriggerList = Array.from(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.forEach((tooltipTriggerEl) => {
            window.bootstrap.Tooltip.getOrCreateInstance(tooltipTriggerEl);
        });
    }
});
