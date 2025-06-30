from django.contrib import admin

from keyopolls.common.models import Category, SubCategory


class SubCategoryInline(admin.TabularInline):
    model = SubCategory
    extra = 1
    prepopulated_fields = {"slug": ("name",)}
    fields = ["name", "slug", "icon", "icon_color", "display_order", "is_active"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "category_type",
        "display_order",
        "is_featured",
        "is_active",
        "has_subcategories",
    ]
    list_filter = [
        "category_type",
        "is_featured",
        "is_active",
        "allows_images",
        "allows_videos",
        "allows_links",
    ]
    search_fields = ["name", "description"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [SubCategoryInline]

    fieldsets = [
        (None, {"fields": ["name", "slug", "description", "category_type"]}),
        (
            "Display Settings",
            {"fields": ["icon", "icon_color", "display_order", "is_featured"]},
        ),
        ("Content Settings", {"fields": ["character_limit"]}),
        (
            "Media Permissions",
            {
                "fields": [
                    "allows_images",
                    "allows_gifs",
                    "allows_videos",
                    "allows_links",
                    "allows_polls",
                    "allows_location",
                    "max_images",
                    "max_video_duration",
                ]
            },
        ),
        ("Tag Settings", {"fields": ["allows_tags", "max_tags"]}),
        ("System Settings", {"fields": ["is_active", "requires_approval"]}),
    ]


@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "display_order", "is_active"]
    list_filter = ["category", "is_active"]
    search_fields = ["name", "description"]
    prepopulated_fields = {"slug": ("name",)}

    fieldsets = [
        (None, {"fields": ["name", "slug", "description", "category"]}),
        (
            "Display Settings",
            {"fields": ["icon", "icon_color", "display_order", "is_active"]},
        ),
    ]
