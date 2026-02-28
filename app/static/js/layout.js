document.addEventListener('DOMContentLoaded', () => {
	const themeToggle = document.getElementById('themeToggle');
	const themeKey = 'unbroken-theme';

	const applyTheme = (theme) => {
		document.documentElement.setAttribute('data-theme', theme);
		if (themeToggle) {
			const nextLabel = theme === 'dark' ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro';
			themeToggle.setAttribute('aria-label', nextLabel);
			themeToggle.setAttribute('title', nextLabel);
		}
	};

	const savedTheme = localStorage.getItem(themeKey);
	applyTheme(savedTheme === 'dark' ? 'dark' : 'light');

	if (themeToggle) {
		themeToggle.addEventListener('click', () => {
			const current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
			const next = current === 'dark' ? 'light' : 'dark';
			applyTheme(next);
			localStorage.setItem(themeKey, next);
		});
	}

	const brandHome = document.getElementById('brandHome');

	if (brandHome) {
		brandHome.addEventListener('click', (event) => {
			const isHome = window.location.pathname === '/';
			if (isHome) {
				event.preventDefault();
				window.scrollTo({ top: 0, behavior: 'smooth' });
			}
		});
	}

	const openButton = document.getElementById('openLoginModal');
	const closeButton = document.getElementById('closeLoginModal');
	const modal = document.getElementById('loginModal');

	if (openButton && modal) {
		const openModal = () => {
			modal.classList.remove('hidden');
		};

		const closeModal = () => {
			modal.classList.add('hidden');
		};

		openButton.addEventListener('click', openModal);

		if (closeButton) {
			closeButton.addEventListener('click', closeModal);
		}

		modal.addEventListener('click', (event) => {
			if (event.target === modal) {
				closeModal();
			}
		});

		document.addEventListener('keydown', (event) => {
			if (event.key === 'Escape' && !modal.classList.contains('hidden')) {
				closeModal();
			}
		});
	}
});