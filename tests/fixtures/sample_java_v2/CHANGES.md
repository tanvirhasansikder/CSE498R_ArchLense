# sample_java_v2: deliberate changes from sample_java (answer key for the comparator)

1. UserService now receives UserRepository through its constructor instead of
   creating `new JdbcUserRepository()`.
   -> removed edge: service.UserService -> repository.JdbcUserRepository
2. The nested class UserService.Cache was deleted.
   -> removed node: service.UserService.Cache
   -> removed edge: service.UserService.Cache -> model.User
3. New class controller.AdminController uses JdbcUserRepository directly.
   -> added node: controller.AdminController
   -> added edges: controller.AdminController -> repository.JdbcUserRepository
                   controller.AdminController -> model.User
4. UserController now receives UserService through its constructor (same reason
   as 1). The edge controller.UserController -> service.UserService still exists
   (field + constructor parameter), so it is unchanged, not added or removed.

All other edges are unchanged: 9 edges before - 2 removed = 7 unchanged.
