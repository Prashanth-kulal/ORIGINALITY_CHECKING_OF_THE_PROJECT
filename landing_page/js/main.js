/* ============================================
   AI-Powered Originality Checking & Student Project Management System
   Landing Page JavaScript
   ============================================ */

/* NOTE: When integrating with your project, update paths and integrate with your backend */

// ===== Initialize on DOM Load =====
document.addEventListener('DOMContentLoaded', function() {
    initParticles();
    initTypingAnimation();
    initScrollAnimations();
    initCounters();
    initCarousel();
    initJourneyTabs();
    initMobileMenu();
    initSmoothScroll();
    initLightbox();
});

// ===== Particle Background =====
function initParticles() {
    const particleContainer = document.getElementById('particles');
    const particleCount = 0;

    if (!particleContainer) {
        return;
    }
    
    for (let i = 0; i < particleCount; i++) {
        const particle = document.createElement('div');
        particle.className = 'particle';
        particle.style.left = Math.random() * 100 + '%';
        particle.style.top = Math.random() * 100 + '%';
        particle.style.animationDelay = Math.random() * 15 + 's';
        particle.style.animationDuration = (Math.random() * 10 + 10) + 's';
        particleContainer.appendChild(particle);
    }
}

// ===== Typing Animation =====
function initTypingAnimation() {
    const typingElement = document.getElementById('typing-text');
    const phrases = [
        'AI-Powered Originality Checking',
        'Intelligent Project Management',
        'Research Paper Analysis',
        'Smart Supervisor Allocation',
        'Real-Time Collaboration'
    ];
    
    let phraseIndex = 0;
    let charIndex = 0;
    let isDeleting = false;
    let typingSpeed = 100;
    
    function type() {
        const currentPhrase = phrases[phraseIndex];
        
        if (isDeleting) {
            typingElement.textContent = currentPhrase.substring(0, charIndex - 1);
            charIndex--;
            typingSpeed = 50;
        } else {
            typingElement.textContent = currentPhrase.substring(0, charIndex + 1);
            charIndex++;
            typingSpeed = 100;
        }
        
        if (!isDeleting && charIndex === currentPhrase.length) {
            isDeleting = true;
            typingSpeed = 2000; // Pause at end
        } else if (isDeleting && charIndex === 0) {
            isDeleting = false;
            phraseIndex = (phraseIndex + 1) % phrases.length;
            typingSpeed = 500; // Pause before new phrase
        }
        
        setTimeout(type, typingSpeed);
    }
    
    type();
}

// ===== Scroll Animations =====
function initScrollAnimations() {
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
            }
        });
    }, observerOptions);
    
    // Observe all sections
    const sections = document.querySelectorAll('section');
    sections.forEach(section => {
        section.classList.add('fade-in');
        observer.observe(section);
    });
    
    // Observe feature cards
    const featureCards = document.querySelectorAll('.feature-card');
    featureCards.forEach((card, index) => {
        card.classList.add('fade-in');
        card.style.transitionDelay = (index * 0.1) + 's';
        observer.observe(card);
    });
    
    // Observe timeline items
    const timelineItems = document.querySelectorAll('.timeline-item');
    timelineItems.forEach((item, index) => {
        item.classList.add('fade-in');
        item.style.transitionDelay = (index * 0.2) + 's';
        observer.observe(item);
    });
    
    // Observe stat cards
    const statCards = document.querySelectorAll('.stat-card');
    statCards.forEach((card, index) => {
        card.classList.add('fade-in');
        card.style.transitionDelay = (index * 0.1) + 's';
        observer.observe(card);
    });
    
    // Observe tech items
    const techItems = document.querySelectorAll('.tech-item');
    techItems.forEach((item, index) => {
        item.classList.add('fade-in');
        item.style.transitionDelay = (index * 0.1) + 's';
        observer.observe(item);
    });

    const previewCards = document.querySelectorAll('.preview-card');
    previewCards.forEach((card, index) => {
        card.classList.add('fade-in');
        card.style.transitionDelay = (index * 0.1) + 's';
        observer.observe(card);
    });

    const galleryItems = document.querySelectorAll('.gallery-item');
    galleryItems.forEach((item, index) => {
        item.classList.add('fade-in');
        item.style.transitionDelay = (index * 0.08) + 's';
        observer.observe(item);
    });
}

// ===== Counter Animation =====
function initCounters() {
    const counters = document.querySelectorAll('.counter');
    const observerOptions = {
        threshold: 0.5
    };
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const counter = entry.target;
                const target = parseInt(counter.getAttribute('data-target'));
                const duration = 2000; // 2 seconds
                const step = target / (duration / 16); // 60fps
                let current = 0;
                
                const updateCounter = () => {
                    current += step;
                    if (current < target) {
                        counter.textContent = Math.floor(current);
                        requestAnimationFrame(updateCounter);
                    } else {
                        counter.textContent = target;
                    }
                };
                
                updateCounter();
                observer.unobserve(counter);
            }
        });
    }, observerOptions);
    
    counters.forEach(counter => observer.observe(counter));
}

// ===== Carousel =====
let currentSlide = 0;
const totalSlides = 3;

function initCarousel() {
    const dots = document.querySelectorAll('.dot');
    
    dots.forEach((dot, index) => {
        dot.addEventListener('click', () => {
            goToSlide(index);
        });
    });
    
    // Auto-advance carousel
    setInterval(() => {
        moveCarousel(1);
    }, 5000);
}

function moveCarousel(direction) {
    const slides = document.querySelectorAll('.carousel-slide');
    const dots = document.querySelectorAll('.dot');
    
    slides[currentSlide].classList.remove('active');
    dots[currentSlide].classList.remove('active');
    
    currentSlide = (currentSlide + direction + totalSlides) % totalSlides;
    
    slides[currentSlide].classList.add('active');
    dots[currentSlide].classList.add('active');
}

function goToSlide(index) {
    const slides = document.querySelectorAll('.carousel-slide');
    const dots = document.querySelectorAll('.dot');
    
    slides[currentSlide].classList.remove('active');
    dots[currentSlide].classList.remove('active');
    
    currentSlide = index;
    
    slides[currentSlide].classList.add('active');
    dots[currentSlide].classList.add('active');
}

// ===== Journey Tabs =====
function initJourneyTabs() {
    const tabs = document.querySelectorAll('.journey-tab');
    const panels = document.querySelectorAll('.journey-panel');
    
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetTab = tab.getAttribute('data-tab');
            
            // Remove active class from all tabs and panels
            tabs.forEach(t => t.classList.remove('active'));
            panels.forEach(p => p.classList.remove('active'));
            
            // Add active class to clicked tab and corresponding panel
            tab.classList.add('active');
            document.getElementById(targetTab + '-panel').classList.add('active');
        });
    });
}

// ===== Mobile Menu =====
function initMobileMenu() {
    const hamburger = document.querySelector('.hamburger');
    const navMenu = document.querySelector('.nav-menu');
    
    hamburger.addEventListener('click', () => {
        navMenu.classList.toggle('active');
        
        // Animate hamburger
        const spans = hamburger.querySelectorAll('span');
        if (navMenu.classList.contains('active')) {
            spans[0].style.transform = 'rotate(45deg) translate(5px, 5px)';
            spans[1].style.opacity = '0';
            spans[2].style.transform = 'rotate(-45deg) translate(7px, -6px)';
        } else {
            spans[0].style.transform = 'none';
            spans[1].style.opacity = '1';
            spans[2].style.transform = 'none';
        }
    });
    
    // Close menu when clicking on a link
    const navLinks = document.querySelectorAll('.nav-menu a');
    navLinks.forEach(link => {
        link.addEventListener('click', () => {
            navMenu.classList.remove('active');
            const spans = hamburger.querySelectorAll('span');
            spans[0].style.transform = 'none';
            spans[1].style.opacity = '1';
            spans[2].style.transform = 'none';
        });
    });
}

// ===== Smooth Scroll =====
function initSmoothScroll() {
    // This function is called globally from HTML onclick attributes
    window.scrollToSection = function(selector) {
        const element = document.querySelector(selector);
        if (element) {
            element.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    };
}

function initLightbox() {
    const lightbox = document.getElementById('lightbox');
    const lightboxImage = document.querySelector('.lightbox-image');
    const closeButton = document.querySelector('.lightbox-close');
    const galleryLinks = document.querySelectorAll('[data-lightbox="system-gallery"]');

    galleryLinks.forEach(link => {
        link.addEventListener('click', function(event) {
            event.preventDefault();
            const imageSrc = this.getAttribute('href');
            lightboxImage.src = imageSrc;
            lightbox.classList.add('active');
            lightbox.setAttribute('aria-hidden', 'false');
        });
    });

    if (closeButton) {
        closeButton.addEventListener('click', function() {
            lightbox.classList.remove('active');
            lightbox.setAttribute('aria-hidden', 'true');
        });
    }

    if (lightbox) {
        lightbox.addEventListener('click', function(event) {
            if (event.target === lightbox) {
                lightbox.classList.remove('active');
                lightbox.setAttribute('aria-hidden', 'true');
            }
        });
    }
}

// ===== Navbar Scroll Effect =====
window.addEventListener('scroll', () => {
    const navbar = document.querySelector('.navbar');
    if (window.scrollY > 50) {
        navbar.style.background = 'rgba(255, 255, 255, 0.98)';
        navbar.style.boxShadow = '0 4px 20px rgba(236, 72, 153, 0.1)';
    } else {
        navbar.style.background = 'rgba(255, 255, 255, 0.95)';
        navbar.style.boxShadow = '0 2px 4px rgba(0, 0, 0, 0.04)';
    }
});

// ===== Get Started Button =====
// NOTE: This button is currently a placeholder. When integrating with your project,
// update this function to redirect to your login page or authentication endpoint.
document.getElementById('get-started-btn').addEventListener('click', function() {
    // Placeholder action - currently does nothing
    // INTEGRATION NOTE: Replace this with your login page redirect
    // Example: window.location.href = '/login';
    
    console.log('Get Started button clicked - Integration required');
    alert('This button will be integrated with your login page during integration.');
});

// ===== Active Navigation Link =====
window.addEventListener('scroll', () => {
    const sections = document.querySelectorAll('section[id]');
    const navLinks = document.querySelectorAll('.nav-menu a');
    
    let current = '';
    
    sections.forEach(section => {
        const sectionTop = section.offsetTop;
        const sectionHeight = section.clientHeight;
        
        if (window.scrollY >= sectionTop - 200) {
            current = section.getAttribute('id');
        }
    });
    
    navLinks.forEach(link => {
        link.style.color = '';
        if (link.getAttribute('href') === '#' + current) {
            link.style.color = '#EC4899';
        }
    });
});

// ===== Parallax Effect for Gradient Mesh =====
window.addEventListener('mousemove', (e) => {
    const meshes = document.querySelectorAll('.mesh-gradient');
    const mouseX = e.clientX / window.innerWidth;
    const mouseY = e.clientY / window.innerHeight;
    
    meshes.forEach((mesh, index) => {
        const speed = (index + 1) * 15;
        const x = (mouseX - 0.5) * speed;
        const y = (mouseY - 0.5) * speed;
        mesh.style.transform = `translate(${x}px, ${y}px)`;
    });
});

// ===== Feature Card Hover Effect Enhancement =====
document.querySelectorAll('.feature-card').forEach(card => {
    card.addEventListener('mouseenter', function() {
        this.style.transform = 'translateY(-10px) scale(1.02)';
    });
    
    card.addEventListener('mouseleave', function() {
        this.style.transform = 'translateY(0) scale(1)';
    });
});

// ===== Tech Item Hover Effect =====
document.querySelectorAll('.tech-item').forEach(item => {
    item.addEventListener('mouseenter', function() {
        const icon = this.querySelector('.tech-icon');
        icon.style.transform = 'rotate(360deg) scale(1.2)';
        icon.style.transition = 'transform 0.5s ease';
    });
    
    item.addEventListener('mouseleave', function() {
        const icon = this.querySelector('.tech-icon');
        icon.style.transform = 'rotate(0deg) scale(1)';
    });
});

// ===== Timeline Item Animation =====
document.querySelectorAll('.timeline-item').forEach(item => {
    item.addEventListener('mouseenter', function() {
        const marker = this.querySelector('.timeline-marker');
        marker.style.transform = 'translateX(-50%) scale(1.2)';
        marker.style.transition = 'transform 0.3s ease';
    });
    
    item.addEventListener('mouseleave', function() {
        const marker = this.querySelector('.timeline-marker');
        marker.style.transform = 'translateX(-50%) scale(1)';
    });
});

// ===== Console Message for Developers =====
console.log('%c AI-Powered Originality Checking & Student Project Management System ', 'background: linear-gradient(135deg, #EC4899, #8B5CF6); color: white; padding: 10px; font-size: 14px; font-weight: bold;');
console.log('%c Premium Pink + Purple Theme Landing Page Loaded Successfully ', 'color: #10B981; font-size: 12px;');
console.log('%c Integration Notes: ', 'color: #F59E0B; font-size: 12px; font-weight: bold;');
console.log('- Update CSS and JS paths when integrating with your project');
console.log('- Connect Get Started button to your login page');
console.log('- Replace placeholder dashboard mockups with actual screenshots');
console.log('- Add your actual API endpoints for backend integration');
