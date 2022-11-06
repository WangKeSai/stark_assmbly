from django import forms
from django.conf.urls import url
import functools
from types import FunctionType
from django.db.models import ForeignKey, ManyToManyField

from django.db.models import Q
from django.shortcuts import HttpResponse, render, redirect
from django.urls import reverse
from django.utils.safestring import mark_safe
from stark.utils.pagination import Pagination
from django.http import QueryDict


def get_choice_text(title, field):
    """
    对于stark组建中定义列时，choice字段如果想要显示中文信息，在自己的类中调用此方法
    例： list_display = ['id', 'title', get_choice_text("等级", 'level'), StarkHandler.display_edit, StarkHandler.display_del]
    :param title:希望页面显示的表头
    :param field:字段名称
    :return:
    """

    def inner(self, obj=None, is_header=None):
        if is_header:
            return title
        method = "get_%s_display" % field
        return getattr(obj, method)

    return inner


class StarkModelForm(forms.ModelForm):
    """
    构造modelform的基类，目的为让每个字段在前端加上样式。
    """

    def __init__(self, *args, **kwargs):
        super(StarkModelForm, self).__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'


class SearchGroupRow(object):
    def __init__(self, queryset_or_tuple, option, title, request):
        self.queryset_or_tuple = queryset_or_tuple
        self.option = option
        self.title = title
        self.request = request

    def __iter__(self):
        yield '<div class="whole">'
        yield self.title
        yield '</div>'

        yield '<div class="others">'

        query_dict = self.request.GET.copy()
        query_dict._mutable = True
        origin_value_list = query_dict.getlist(self.option.field)
        if not origin_value_list:
            yield "<a href='?%s' class='active'>全部</a>" % query_dict.urlencode()
        else:
            query_dict.pop(self.option.field)
            yield "<a href='?%s'>全部</a>" % query_dict.urlencode()
        for item in self.queryset_or_tuple:
            text = self.option.get_text(item)
            value = str(self.option.get_value(item))
            query_dict = self.request.GET.copy()
            query_dict._mutable = True
            if not self.option.is_multi:
                query_dict[self.option.field] = value
                if value in origin_value_list:
                    query_dict.pop(self.option.field)
                    yield "<a href='?%s' class='active'>%s</a>" % (query_dict.urlencode(), text)
                else:
                    yield "<a href='?%s'>%s</a>" % (query_dict.urlencode(), text)
            else:
                mutil_value_list = query_dict.getlist(self.option.field)
                if value in mutil_value_list:
                    mutil_value_list.remove(value)
                    query_dict.setlist(self.option.field, mutil_value_list)
                    yield "<a href='?%s' class='active'>%s</a>" % (query_dict.urlencode(), text)
                else:
                    mutil_value_list.append(value)
                    query_dict.setlist(self.option.field, mutil_value_list)
                    yield "<a href='?%s'>%s</a>" % (query_dict.urlencode(), text)

        yield '</div>'


class Option(object):
    """用于构建多条件筛选对象"""
    def __init__(self, field, db_condition=None, text_func=None, value_func=None, is_multi=False):
        """

        :param field:组合搜索关联的字段
        :param db_condition:数据库关联查询时的条件
        """
        self.field = field
        if not db_condition:
            db_condition = {}
        self.db_condition = db_condition
        self.text_func = text_func
        self.value_func = value_func
        self.is_multi = is_multi
        self.is_choice = False

    def get_db_condition(self, request, *args, **kwargs):
        """
        获取筛选条件
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        return self.db_condition

    def get_queryset_or_tuple(self, model_class, request, *args, **kwargs):
        """
        根据字段去获取数据库相关联的数据
        :param model_class:
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        field_object = model_class._meta.get_field(self.field)
        title = field_object.verbose_name
        db_condition = self.get_db_condition(request, *args, **kwargs)
        if isinstance(field_object, ForeignKey) or isinstance(field_object, ManyToManyField):
            return SearchGroupRow(field_object.related_model.objects.filter(**db_condition), self, title, request)
        else:
            self.is_choice = True
            return SearchGroupRow(field_object.choices, self, title, request)

    def get_text(self, field_object):
        """
        获取筛选条件的中文文本，用于显示在前端。
        choice字段获取该字段的中文
        联表字段获取表的__str__方法返回的值
        :param field_object:
        :return:
        """
        if self.text_func:
            return self.text_func(field_object)
        if self.is_choice:
            return field_object[1]
        return str(field_object)

    def get_value(self, field_object):
        """
        获取筛选条件在数据库存储的值
        :param field_object:
        :return:
        """
        if self.value_func:
            return self.value_func(field_object)
        if self.is_choice:
            return field_object[0]
        return field_object.pk


class StarkHandler(object):
    """stark基类"""

    def __init__(self, model_class, prev, site):
        """
        初始化方法
        :param model_class: 数据表模型类
        :param prev: url前缀
        :param site: site实例化对象
        """
        self.site = site
        self.model_class = model_class
        self.prev = prev
        self.request = None

    per_page_count = 10  # 用于分页时每页现实的数据条数，可在子类中自行定制。

    ########################## 列表页面需要展示的列 ####################

    list_display = []   # 列表页面需要展示的列

    def get_list_display(self):
        """
        自定义页面要显示的列，预留的自定义扩展，以后可根据用户不同，显示不同的列
        :return:
        """
        value = []
        value.extend(self.list_display)
        return value

    def display_check(self, obj=None, is_header=None):
        """
        多选框列， 可在子类中将此函数加入list_display列表中，即可在页面上显示多选框列。
        :param obj:每条数据的对象
        :param is_header:是否为标题
        :return:标题或者CheckBox
        """
        if is_header:
            return "选择"
        return mark_safe('<input type="checkbox" name="pk" value="%s" />' % obj.pk)

    def display_edit(self, obj=None, is_header=None):
        """
        编辑方法列， 可在子类中将此函数加入list_display列表中，即可在页面上显示编辑列。
        :param obj:每条数据的对象
        :param is_header:是否为标题
        :return:标题或者编辑按钮
        """
        if is_header:
            return "编辑"
        edit_url = self.reverse_url(self.get_change_url_name, obj_id=(obj.id,))
        return mark_safe("<a href='%s'>编辑</a>" % edit_url)

    def display_del(self, obj=None, is_header=None):
        """
        删除方法列， 可在子类中将此函数加入list_display列表中，即可在页面上显示删除列。
        :param obj:每条数据的对象
        :param is_header:是否为标题
        :return:标题或者删除按钮
        """
        if is_header:
            return "删除"
        delete_url = self.reverse_url(self.get_delete_url_name, obj_id=(obj.id,))
        return mark_safe("<a href='%s'>删除</a>" % delete_url)

    #-----------------------------------------------------------------#




    ########################### 添加按钮控制 ###########################

    has_add_btn = True     # 是否显示添加数据按钮，可用于权限控制，根据用户不同，是否展示添加按钮。可在子类中自行定制

    def get_add_btn(self):
        """
        生成添加按钮函数。
        :return: 默认返回添加按钮，如在子类中定义不展示添加按钮，则返回none
        """
        if self.has_add_btn:
            add_url = self.reverse_url(self.get_add_url_name, obj_id=None)
            return "<a class='btn btn-primary' href='%s'>添加</a>" % add_url
        return None

    #-----------------------------------------------------------------#





    ######################### 获取modelform类 #########################

    model_form_class = None          # 数据库表模型Form类，可在子类中自行定义modelform

    def get_model_form_class(self):
        """
        获取数据库表模型Form类，并继承StarkModelForm，为字段加上前端样式
        :return:
        """
        if self.model_form_class:
            return self.model_form_class

        class DynamicModelForm(StarkModelForm):
            class Meta:
                model = self.model_class
                fields = '__all__'

        return DynamicModelForm

    def save(self, form, is_update=False):
        """
        编辑或新增数据时，通过form对象进行新增或修改数据函数
        可在子类中重写该方法，例如在保存数据时有一部分数据是不让用户输入，而是系统默认设置的就需要重写该方法
        :param form:
        :param is_update:
        :return:
        """
        form.save()

    # -----------------------------------------------------------------#






    ############################## 排序字段设置 ########################

    order_list = []   # 默认排序字段， 可在子类中自行定制，若不定制，则按数据表中的id倒序排序

    def get_order_list(self):
        """
        获取排序字段
        :return:
        """
        return self.order_list or ['-id', ]
    #-----------------------------------------------------------------#





    ############################## 搜索条件字段设置 ####################

    search_list = []   # 搜索框搜索条件的字段，可在子类中自行定制，例：search_list = ['name__contains'，]；若不定制，则不显示搜索框

    def get_search_list(self):
        """
        获取搜索条件字段列表
        :return: 搜索条件字段列表
        """
        return self.search_list
    #-----------------------------------------------------------------#





    ######################### 批量操作设置 ###############################
    action_list = []   # 批量操作方法列表，可在子类中自行定制，若不定制，则前端不显示批量操作下拉框， 列表中存储批量操作函数

    def get_action_list(self):
        """
        获取批量操作方法列表
        :return: 批量操作方法列表
        """
        return self.action_list

    def action_multi_delete(self, request):
        """
        批量删除  如果想在执行完之后返回特定的值或跳转到别的页面， 那么在该函数添加返回值即可。
        若想使用此功能，在子类中将此函数添加到action_list列表中即可
        也可在子类中自定义其他批量操作函数，并将其添加到action_list列表中。
        :param request:
        :return:
        """
        pk_list = request.POST.getlist("pk")
        self.model_class.objects.filter(id__in=pk_list).delete()

    action_multi_delete.text = '批量删除'   # 函数中文名称，用于前端页面显示批量操作的名称
    # -----------------------------------------------------------------#




    ############################## 多条件筛选设置 #######################
    search_group = []  # 用于筛选的字段的option对象列表
    """
    例：
        search_group = [
            Option("gender"),
            Option("depart", {"id__gt":2}, is_multi=True)
        ]
    """

    def get_search_group(self):
        """
        获取筛选的字段的option对象列表
        :return: 筛选的字段的option对象列表
        """
        return self.search_group

    def get_search_group_condition(self, request):
        """
        从url的参数中获取筛选条件
        :param request:
        :return:
        """
        condition = {}
        for option in self.get_search_group():
            if option.is_multi:
                value_list = request.GET.getlist(option.field)
                if not value_list:
                    continue
                condition["%s__in" % option.field] = value_list
            else:
                value = request.GET.get(option.field)
                if not value:
                    continue
                condition[option.field] = value
        return condition

    # -----------------------------------------------------------------#





    ############################### 视图函数 #########################

    def changelist_view(self, request, *args, **kwargs):
        """
        列表页面视图函数
        :param request:
        :return:
        """
        self.request = request
        ########################### 显示列 #############################
        list_display = self.get_list_display()
        header_list = []
        if list_display:
            for key_or_func in list_display:
                if isinstance(key_or_func, FunctionType):
                    verbose_name = key_or_func(self, obj=None, is_header=True)
                else:
                    verbose_name = self.model_class._meta.get_field(key_or_func).verbose_name
                header_list.append(verbose_name)
        else:
            header_list.append(self.model_class._meta.model_name)

        ############################ 组合筛选 #############################

        search_group = self.get_search_group()
        search_group_row_list = []
        for option_object in search_group:
            queryset_or_tuple = option_object.get_queryset_or_tuple(self.model_class, request, *args, **kwargs)
            search_group_row_list.append(queryset_or_tuple)

        ############################ 多选action #############################
        action_list = self.get_action_list()
        action_dict = {func.__name__: func.text for func in action_list}

        if request.method == 'POST':
            action_func_name = request.POST.get("action")
            if action_func_name and action_func_name in action_dict:
                action_response = getattr(self, action_func_name)(request, *args, **kwargs)
                if action_response:
                    return action_response
        ############################ 模糊搜索 #############################
        search_list = self.get_search_list()
        search_value = request.GET.get("q", '')
        conn = Q()
        conn.connector = 'OR'
        if search_value:
            for item in search_list:
                conn.children.append((item, search_value))

        ############################ 获取排序 #############################

        order_list = self.get_order_list()

        ############################ 分页操作 #############################

        search_group_condition = self.get_search_group_condition(request)
        queryset = self.model_class.objects.filter(conn).filter(**search_group_condition).order_by(*order_list)

        all_count = queryset.count()
        query_params = request.GET.copy()
        query_params._mutable = True

        pagination = Pagination(current_page=request.GET.get("page"),
                                all_count=all_count,
                                base_url=request.path_info,
                                query_params=query_params,
                                per_page=self.per_page_count, )

        data_list = queryset[pagination.start:pagination.end]

        ############################ 数据处理 #############################

        body_list = []
        for row in data_list:
            tr_list = []
            if list_display:
                for key_or_func in list_display:
                    if isinstance(key_or_func, FunctionType):
                        tr_list.append(key_or_func(self, row, is_header=False))
                    else:
                        tr_list.append(getattr(row, key_or_func))
            else:
                tr_list.append(row)
            body_list.append(tr_list)

        ############################# 添加按钮 #############################
        add_btn = self.get_add_btn()

        return render(request, 'stark/change_list.html',
                      {"header_list": header_list,
                       "body_list": body_list,
                       "pagination": pagination,
                       "add_btn": add_btn,
                       "search_list": search_list,
                       "search_value": search_value,
                       "action_dict": action_dict,
                       "search_group_row_list": search_group_row_list, })

    def add_view(self, request, *args, **kwargs):
        """
        添加页面视图函数
        :param request:
        :return:
        """
        model_form_class = self.get_model_form_class()
        if request.method == 'GET':
            form = model_form_class()
            return render(request, 'stark/change.html', {"form": form})
        form = model_form_class(data=request.POST)
        if form.is_valid():
            self.save(form, is_update=False)
            return redirect(self.revers_list_url())
        return render(request, 'stark/change.html', {"form": form})

    def change_view(self, request, pk, *args, **kwargs):
        """
        编辑页面视图函数
        :param request:
        :param pk:
        :return:
        """
        obj = self.model_class.objects.filter(pk=pk).first()
        if not obj:
            return HttpResponse("要修改的数据不存在，请重新选择！")
        model_form_class = self.get_model_form_class()
        if request.method == 'GET':
            form = model_form_class(instance=obj)
            return render(request, 'stark/change.html', {"form": form})
        form = model_form_class(data=request.POST, instance=obj)
        if form.is_valid():
            self.save(form, is_update=False)
            return redirect(self.revers_list_url())
        return render(request, 'stark/change.html', {"form": form})

    def delete_view(self, request, pk, *args, **kwargs):
        """
        删除页面视图函数
        :param request:
        :param pk:
        :return:
        """
        if request.method == 'GET':
            return render(request, 'stark/delete.html', {"cancel": self.revers_list_url()})
        self.model_class.objects.filter(pk=pk).first().delete()
        return redirect(self.revers_list_url())

    #-----------------------------------------------------------------#




    ############################ url别名操作 #########################

    def get_url_name(self, param):
        """
        生成url的别名
        :param param:
        :return:
        """
        app_label, model_name = self.model_class._meta.app_label, self.model_class._meta.model_name
        if self.prev:
            return '%s_%s_%s_%s' % (app_label, model_name, self.prev, param)
        return '%s_%s_%s' % (app_label, model_name, param)

    @property
    def get_list_url_name(self):
        """
        获取到列表页面的url的name别名
        :return:
        """
        return self.get_url_name('list')

    @property
    def get_add_url_name(self):
        """
        获取到添加页面的url的name别名
        :return:
        """
        return self.get_url_name('add')

    @property
    def get_change_url_name(self):
        """
        获取到编辑页面的url的name别名
        :return:
        """
        return self.get_url_name('change')

    @property
    def get_delete_url_name(self):
        """
        获取到删除页面的url的name别名
        :return:
        """
        return self.get_url_name('delete')

    #-----------------------------------------------------------------#





    ###################### 用于处理携带参数的url #########################
    def reverse_url(self, url_name, obj_id):
        """
        将原带参数的url中的参数包装给_filter参数，以便在返回页面时能够不丢失原来url的参数
        :param url_name:
        :param obj_id:
        :return:
        """
        name = '%s:%s' % (self.site.namespace, url_name)
        if obj_id:
            base_url = reverse(name, args=obj_id)
        else:
            base_url = reverse(name)
        if not self.request:
            all_url = base_url
        else:
            param = self.request.GET.urlencode()
            new_query_dict = QueryDict(mutable=True)
            new_query_dict['_filter'] = param
            all_url = "%s?%s" % (base_url, new_query_dict.urlencode())
        return all_url

    def revers_list_url(self):
        """
        获取到原来的url里的参数，并重新生成url
        :return:
        """
        name = '%s:%s' % (self.site.namespace, self.get_list_url_name)
        base_url = reverse(name)
        param = self.request.GET.get("_filter")
        if not param:
            return base_url
        return "%s?%s" % (base_url, param)
    #-----------------------------------------------------------------#





    ############## 生成增删改查的url，还可自定制添加其他url ##############

    def wrapper(self, func):
        """
        闭包函数，用于在每次生成增删改查url时将每个视图函数的request复制给self.request
        :param func: 视图函数
        :return:
        """
        @functools.wraps(func)
        def inner(request, *args, **kwargs):
            self.request = request
            return func(request, *args, **kwargs)

        return inner

    def get_urls(self):
        """
        生成四个增删改查url
        :return:
        """

        patterns = [
            url(r'list/$', self.wrapper(self.changelist_view), name=self.get_list_url_name),
            url(r'add/$', self.wrapper(self.add_view), name=self.get_add_url_name),
            url(r'change/(?P<pk>\d+)/$', self.wrapper(self.change_view), name=self.get_change_url_name),
            url(r'delete/(?P<pk>\d+)/$', self.wrapper(self.delete_view), name=self.get_delete_url_name),
        ]
        patterns.extend(self.extra_urls())
        return patterns

    def extra_urls(self):
        """
        扩展自定义url，可在子类中重写该方法，添加其他自己想添加的url
        :return:
        """
        return []

    #-----------------------------------------------------------------#


class StarkSite(object):

    def __init__(self):
        self._registry = []
        self.app_name = 'stark'
        self.namespace = 'stark'

    def register(self, model_class, handler_class=None, prev=None):
        """

        :param model_class: 是models中的数据库表对应的类
        :param handler_class: 处理请求的视图函数所对应的类
        :param prev: 生成url时的前缀， 默认为none
        :return:
        """
        if not handler_class:
            handler_class = StarkHandler

        self._registry.append(
            {"model_class": model_class, "handler": handler_class(model_class, prev, self), "prev": prev})

    def get_urls(self):
        patterns = []
        for item in self._registry:
            model_class = item["model_class"]
            handler = item['handler']
            prev = item['prev']
            app_label, model_name = model_class._meta.app_label, model_class._meta.model_name

            if prev:
                patterns.append(url(r'%s/%s/%s/' % (app_label, model_name, prev), (handler.get_urls(), None, None)))

            else:
                patterns.append(url(r'%s/%s/' % (app_label, model_name), (handler.get_urls(), None, None)))
        return patterns

    @property
    def urls(self):
        return self.get_urls(), self.app_name, self.namespace


site = StarkSite()
