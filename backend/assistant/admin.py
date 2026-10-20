from django.contrib import admin

from .models import AIConversation, AIKnowledgeBase, AIMessage

admin.site.register(AIKnowledgeBase)
admin.site.register(AIConversation)
admin.site.register(AIMessage)
