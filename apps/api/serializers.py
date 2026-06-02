from rest_framework import serializers


class MessageRequestSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    name = serializers.CharField(required=False, default="کاربر", max_length=255)
    message = serializers.CharField(min_length=1)


class UserSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    name = serializers.CharField()
    segment = serializers.CharField()
    created_at = serializers.DateTimeField()
    last_seen_at = serializers.DateTimeField()


class MessageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    user_message = serializers.CharField()
    assistant_reply = serializers.CharField()
    intent = serializers.CharField()
    needs_human_support = serializers.BooleanField()
    created_at = serializers.DateTimeField()
