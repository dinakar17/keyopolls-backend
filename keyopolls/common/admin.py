from django.contrib import admin

from keyopolls.common.models import Category


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "category_type",
        "created_at",
        "updated_at",
    ]
    list_filter = [
        "category_type",
        "created_at",
    ]
    search_fields = ["name", "description"]
    prepopulated_fields = {"slug": ("name",)}

    fieldsets = [
        (None, {"fields": ["name", "slug", "description", "category_type"]}),
        (
            "Timestamps",
            {
                "fields": ["created_at", "updated_at"],
                "classes": ["collapse"],
            },
        ),
    ]

    readonly_fields = ["created_at", "updated_at"]
