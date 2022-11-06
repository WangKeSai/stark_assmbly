from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class StarkConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stark'


    """
    # 重写ready方法，在执行路由分发之前去每个app的目录下寻找stark.py文件并执行。
    # 若想使用stark组件,需要在每个业务app中创建stark.py文件，然后可自行定制
    不定制例子：
        # app01/stark.py
            from stark.service.v1 import site
            from app02 import models
            
            site.register(models.Host, )
    自行定制例子：
        # app01/stark.py
            from stark.service.v1 import site, StarkHandler, Option, get_choice_text, StarkModelForm
            from app01 import models
            
            
            class UserInfoModelForm(StarkModelForm):
                class Meta:
                    model = models.UserInfo
                    fields = ['name', 'age', 'email', 'depart']
            
            
            class UserInfoHandler(StarkHandler):
                list_display = [StarkHandler.display_check, 'name', 'age', get_choice_text("性别", 'gender'), 'email', 'phone', 'depart', StarkHandler.display_edit,
                                StarkHandler.display_del]
            
                order_list = ['id']
            
                search_list = ['name__contains']
            
                search_group = [
                    Option("gender"),
                    Option("depart", {"id__gt":2}, is_multi=True)
                ]
            
                model_form_class = UserInfoModelForm
            
                def save(self, form, is_update=False):
                    form.instance.phone = '111111'
                    form.save()
            
            
                action_list = [StarkHandler.action_multi_delete, ]
            
            
            site.register(models.UserInfo, UserInfoHandler)
    """
    def ready(self):
        autodiscover_modules('stark')
