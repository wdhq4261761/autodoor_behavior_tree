import customtkinter as ctk


class Theme:
    COLORS = {
        'primary': '#3B82F6',
        'primary_hover': '#2563EB',
        'secondary': '#6366F1',
        'success': '#22C55E',
        'success_light': '#DCFCE7',
        'warning': '#F59E0B',
        'warning_light': '#FEF3C7',
        'error': '#EF4444',
        'error_light': '#FEE2E2',
        'info': '#3B82F6',
        'info_hover': '#2563EB',
        'info_light': '#DBEAFE',
        
        'text_primary': '#1F2937',
        'text_secondary': '#6B7280',
        'text_muted': '#9CA3AF',
        
        'bg_primary': '#FFFFFF',
        'bg_secondary': '#F9FAFB',
        'bg_tertiary': '#F3F4F6',
        
        'border': '#E5E7EB',
        'border_light': '#F3F4F6',
        
        'card_bg': '#FFFFFF',
        'sidebar_bg': '#F9FAFB',
        'header_bg': '#FFFFFF',
        'footer_bg': '#F9FAFB',
    }
    
    DARK_COLORS = {
        'primary': '#3B82F6',
        'primary_hover': '#60A5FA',
        'secondary': '#818CF8',
        'success': '#22C55E',
        'success_light': '#166534',
        'warning': '#F59E0B',
        'warning_light': '#92400E',
        'error': '#EF4444',
        'error_light': '#991B1B',
        'info': '#3B82F6',
        'info_hover': '#60A5FA',
        'info_light': '#1E3A8A',
        
        'text_primary': '#F9FAFB',
        'text_secondary': '#D1D5DB',
        'text_muted': '#9CA3AF',
        
        'bg_primary': '#0F172A',
        'bg_secondary': '#1E293B',
        'bg_tertiary': '#334155',
        'bg_elevated': '#1E293B',
        
        'border': '#334155',
        'border_light': '#475569',
        
        'card_bg': '#1E293B',
        'sidebar_bg': '#0F172A',
        'header_bg': '#1E293B',
        'footer_bg': '#0F172A',
        
        'canvas_bg': '#0F172A',
        'canvas_grid': '#1E293B',
        'node_bg': '#1E293B',
        'node_border': '#475569',
        'node_selected': '#3B82F6',
        'connection_line': '#475569',
    }
    
    FONTS = {
        'family': 'Microsoft YaHei',
        'sizes': {
            'xs': 10,
            'sm': 11,
            'base': 12,
            'lg': 14,
            'xl': 16,
            '2xl': 18,
            '3xl': 24,
        },
        'code_family': 'Consolas',
        'code_size': 14,
    }
    
    DIMENSIONS = {
        'sidebar_width': 200,
        'property_width': 260,
        'header_height': 48,
        'footer_height': 32,
        'card_corner_radius': 8,
        'button_corner_radius': 6,
        'input_height': 32,
        'button_height': 36,
        'thumbnail_height': 140,
        'spacing_xs': 4,
        'spacing_sm': 8,
        'spacing_md': 12,
        'spacing_lg': 16,
        'spacing_xl': 24,
    }
    
    NODE_COLORS = {
        'composite': {'bg': '#1E40AF', 'hover': '#1E3A8A', 'text': '#FFFFFF'},
        'decorator': {'bg': '#B45309', 'hover': '#92400E', 'text': '#FFFFFF'},
        'condition': {'bg': '#BE185D', 'hover': '#9D174D', 'text': '#FFFFFF'},
        'action': {'bg': '#047857', 'hover': '#065F46', 'text': '#FFFFFF'},
        'start': {'bg': '#F59E0B', 'hover': '#D97706', 'text': '#FFFFFF'},
        'interface': {'bg': '#8B5CF6', 'hover': '#7C3AED', 'text': '#FFFFFF'},
        'plugin': {'bg': '#6B7280', 'hover': '#4B5563', 'text': '#FFFFFF'},
    }
    
    @classmethod
    def get_font(cls, size_key='base'):
        size = cls.FONTS['sizes'].get(size_key, 12)
        return (cls.FONTS['family'], size)
    
    @classmethod
    def get_code_font(cls):
        return (cls.FONTS['code_family'], cls.FONTS['code_size'])
    
    @classmethod
    def get_dark_colors(cls):
        return cls.DARK_COLORS
    
    @classmethod
    def get_node_color(cls, category: str) -> dict:
        return cls.NODE_COLORS.get(category, cls.NODE_COLORS['action'])


def init_theme():
    ctk.set_appearance_mode('Dark')
    ctk.set_default_color_theme('blue')
    
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
