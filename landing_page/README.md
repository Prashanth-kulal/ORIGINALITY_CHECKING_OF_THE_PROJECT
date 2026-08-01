# AI-Powered Originality Checking & Student Project Management System
## Landing Page

A premium, standalone landing page for the AI-Powered Originality Checking & Student Project Management System.

### 📁 Folder Structure

```
landing_page/
├── index.html              # Main HTML file
├── css/
│   └── style.css          # All styles and animations
├── js/
│   └── main.js            # Interactive JavaScript
├── assets/
│   └── images/            # Placeholder for images
└── README.md              # This file
```

### 🚀 How to Use

1. **Open the landing page:**
   - Simply open `index.html` in a web browser
   - No server required - it's a static HTML page

2. **Integration with your project:**
   - Move the `landing_page` folder to your desired location
   - Update CSS and JS paths in `index.html` to match your project structure
   - Connect the "Get Started" button to your login page

### ✨ Features

- **Hero Section:** Animated gradient background, floating particles, glassmorphism, typing animation
- **Workflow Timeline:** 7-step project lifecycle visualization
- **Feature Showcase:** 12 feature cards with hover animations
- **Animated Statistics:** Counter animations for platform stats
- **User Journey:** Tabbed interface for Student, Faculty, and Coordinator roles
- **Technology Stack:** 10 technology badges with hover effects
- **Dashboard Preview:** Carousel with 3 dashboard mockups (Student, Faculty, Coordinator)
- **Comparison Table:** Traditional vs AI-Powered platform comparison
- **CTA Section:** Call-to-action with placeholder button

### 🎨 Design Features

- Dark futuristic theme with blue and violet gradients
- Glassmorphism UI elements
- Smooth scroll navigation
- Professional typography (Inter & Space Grotesk fonts)
- Subtle glow effects
- Modern Font Awesome icons
- Hover animations on all interactive elements
- Scroll-triggered fade-in animations
- Fully responsive (desktop, tablet, mobile)

### 🔧 Integration Notes

#### 1. Update Paths
When integrating with your project, update these paths in `index.html`:

```html
<!-- Line 13: Update CSS path -->
<link rel="stylesheet" href="css/style.css">

<!-- Line 281: Update JS path -->
<script src="js/main.js"></script>
```

#### 2. Connect Get Started Button
In `js/main.js`, line 234, update the button click handler:

```javascript
// Current (placeholder):
document.getElementById('get-started-btn').addEventListener('click', function() {
    console.log('Get Started button clicked - Integration required');
    alert('This button will be integrated with your login page during integration.');
});

// After integration:
document.getElementById('get-started-btn').addEventListener('click', function() {
    window.location.href = '/login';  // Your login page path
});
```

#### 3. Replace Dashboard Mockups
The dashboard preview section uses CSS-based mockups. To use actual screenshots:

1. Add your screenshot images to `assets/images/`
2. Update the `.dashboard-mockup` CSS in `css/style.css` to use background images
3. Or modify the HTML structure to use `<img>` tags

#### 4. Add Backend Integration
When ready to connect to your Flask backend:

1. Add API calls to `js/main.js` for dynamic data
2. Replace static content with data from your MongoDB database
3. Add authentication checks for protected sections
4. Connect the real-time chat to your Socket.IO implementation

### 📱 Responsive Breakpoints

- **Desktop:** > 1024px
- **Tablet:** 768px - 1024px
- **Mobile:** < 768px
- **Small Mobile:** < 480px

### 🎯 Customization

#### Colors
Edit CSS variables in `css/style.css` (lines 8-38):

```css
:root {
    --primary-color: #6366f1;
    --secondary-color: #8b5cf6;
    --accent-color: #06b6d4;
    /* ... more variables */
}
```

#### Typography
Fonts are loaded from Google Fonts (Inter & Space Grotesk). To change:

1. Update Google Fonts URL in `index.html` (lines 10-12)
2. Update font-family in `css/style.css`

#### Animations
Adjust animation speeds and effects in `css/style.css`:
- Typing animation: `js/main.js` (lines 30-70)
- Scroll animations: `js/main.js` (lines 75-120)
- Counter animations: `js/main.js` (lines 125-150)
- Carousel timing: `js/main.js` (line 175)

### 🔍 Browser Support

- Chrome/Edge: ✅ Full support
- Firefox: ✅ Full support
- Safari: ✅ Full support
- IE11: ❌ Not supported (uses modern CSS features)

### 📝 External Dependencies

- **Google Fonts:** Inter & Space Grotesk
- **Font Awesome:** 6.4.0 (CDN)
- **No JavaScript frameworks** - Pure vanilla JS

### 🚀 Performance

- Lightweight: ~50KB total (HTML + CSS + JS)
- No build process required
- Optimized animations using CSS transforms
- Lazy loading ready (add `loading="lazy"` to images when added)

### 📄 License

This landing page is part of the AI-Powered Originality Checking & Student Project Management System project.

### 🤝 Support

For integration issues or questions, refer to the code comments in each file. Key sections are marked with `NOTE:` comments for easy identification during integration.

---

**Built with ❤️ for modern academic project management**
