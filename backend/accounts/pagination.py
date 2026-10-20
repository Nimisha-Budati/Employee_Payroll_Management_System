from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


def maybe_paginate(request, queryset, serializer_class, **serializer_kwargs):
    """Paginate when the client sends ``?page=``; otherwise return the full list.

    Keeping the unpaginated shape available makes it easy for small dropdowns and
    exports to reuse the same endpoint as the paginated data tables.
    """
    from rest_framework.response import Response

    if 'page' in request.query_params:
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = serializer_class(page, many=True, **serializer_kwargs)
        return paginator.get_paginated_response(serializer.data)
    return Response(serializer_class(queryset, many=True, **serializer_kwargs).data)
