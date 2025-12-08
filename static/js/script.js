// 等待DOM加载完成
document.addEventListener('DOMContentLoaded', function() {
    // 获取导航栏和切换按钮
    const sidebar = document.getElementById('sidebar');
    const toggleBtn = document.getElementById('toggleBtn');
    const resizer = document.getElementById('sidebarResizer');
    const defaultSidebarWidth = 250;
    const collapsedWidth = 70;
    const minSidebarWidth = 180;
    const maxSidebarWidth = 420;
    
    // 检查本地存储中的导航栏状态
    const sidebarState = localStorage.getItem('sidebarCollapsed');
    if (sidebarState === 'true') {
        sidebar.classList.add('collapsed');
        sidebar.style.width = `${collapsedWidth}px`;
    }
    const savedWidth = localStorage.getItem('sidebarWidth');
    if (savedWidth && !sidebar.classList.contains('collapsed')) {
        sidebar.style.width = `${Math.min(Math.max(parseInt(savedWidth, 10), minSidebarWidth), maxSidebarWidth)}px`;
    } else if (!sidebar.classList.contains('collapsed')) {
        sidebar.style.width = `${defaultSidebarWidth}px`;
    }
    
    // 切换导航栏收缩状态
    toggleBtn.addEventListener('click', function() {
        sidebar.classList.toggle('collapsed');
        
        // 保存状态到本地存储
        const isCollapsed = sidebar.classList.contains('collapsed');
        localStorage.setItem('sidebarCollapsed', isCollapsed);
        
        // 添加动画效果
        sidebar.style.transition = 'width 0.3s ease';
        if (isCollapsed) {
            sidebar.style.width = `${collapsedWidth}px`;
        } else {
            const widthToSet = savedWidth ? parseInt(savedWidth, 10) : defaultSidebarWidth;
            sidebar.style.width = `${Math.min(Math.max(widthToSet, minSidebarWidth), maxSidebarWidth)}px`;
        }
    });

    // 侧边栏拖拽缩放
    if (resizer) {
        let isDragging = false;
        const startDrag = (e) => {
            if (sidebar.classList.contains('collapsed')) {
                sidebar.classList.remove('collapsed');
                localStorage.setItem('sidebarCollapsed', false);
            }
            isDragging = true;
            document.body.style.userSelect = 'none';
            document.body.style.cursor = 'col-resize';
        };
        const onDrag = (e) => {
            if (!isDragging) return;
            const newWidth = Math.min(Math.max(e.clientX, minSidebarWidth), maxSidebarWidth);
            sidebar.style.width = `${newWidth}px`;
        };
        const endDrag = () => {
            if (!isDragging) return;
            isDragging = false;
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
            const finalWidth = parseInt(sidebar.getBoundingClientRect().width, 10);
            localStorage.setItem('sidebarWidth', finalWidth);
        };
        resizer.addEventListener('mousedown', startDrag);
        resizer.addEventListener('touchstart', (e) => startDrag(e.touches[0]));
        window.addEventListener('mousemove', onDrag);
        window.addEventListener('touchmove', (e) => onDrag(e.touches[0]));
        window.addEventListener('mouseup', endDrag);
        window.addEventListener('touchend', endDrag);
    }
    
    // 导航链接点击效果
    const navLinks = document.querySelectorAll('.nav-link');
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            // 移除所有active类
            navLinks.forEach(l => l.classList.remove('active'));
            // 给当前点击的链接添加active类
            this.classList.add('active');
        });
        
        // 悬停效果
        link.addEventListener('mouseenter', function() {
            if (!this.classList.contains('active')) {
                this.style.transform = 'translateX(5px)';
            }
        });
        
        link.addEventListener('mouseleave', function() {
            this.style.transform = 'translateX(0)';
        });
    });
    
    // 移动端适配
    function handleMobileView() {
        if (window.innerWidth <= 768) {
            sidebar.classList.add('collapsed');
        }
    }
    
    // 监听窗口大小变化
    window.addEventListener('resize', handleMobileView);
    
    // 初始检查
    handleMobileView();
    
    // 添加页面加载动画
    const contentCards = document.querySelectorAll('.welcome-card, .content-card');
    contentCards.forEach((card, index) => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(20px)';
        
        setTimeout(() => {
            card.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
            card.style.opacity = '1';
            card.style.transform = 'translateY(0)';
        }, index * 200);
    });
    
    // 功能卡片悬停效果
    const featureItems = document.querySelectorAll('.feature-item');
    featureItems.forEach(item => {
        item.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-5px) scale(1.02)';
        });
        
        item.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0) scale(1)';
        });
    });
    
    // 平滑滚动效果
    const links = document.querySelectorAll('a[href^="#"]');
    links.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
});

// 工具函数：显示通知消息
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    // 样式
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 20px;
        border-radius: 5px;
        color: white;
        font-weight: 500;
        z-index: 9999;
        opacity: 0;
        transform: translateX(100px);
        transition: all 0.3s ease;
    `;
    
    // 根据类型设置背景色
    switch(type) {
        case 'success':
            notification.style.backgroundColor = '#28a745';
            break;
        case 'error':
            notification.style.backgroundColor = '#dc3545';
            break;
        case 'warning':
            notification.style.backgroundColor = '#ffc107';
            notification.style.color = '#212529';
            break;
        default:
            notification.style.backgroundColor = '#17a2b8';
    }
    
    document.body.appendChild(notification);
    
    // 显示动画
    setTimeout(() => {
        notification.style.opacity = '1';
        notification.style.transform = 'translateX(0)';
    }, 100);
    
    // 自动消失
    setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transform = 'translateX(100px)';
        setTimeout(() => {
            document.body.removeChild(notification);
        }, 300);
    }, 3000);
}

// 页面加载完成后的初始化
window.addEventListener('load', function() {
    // 显示欢迎消息
    setTimeout(() => {
        showNotification('欢迎使用无人集群指控系统！', 'success');
    }, 1000);
});
