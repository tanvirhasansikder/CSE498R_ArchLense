package com.example.controller;

import com.example.service.UserService;
import com.example.model.User;

public class UserController {
    private final UserService<String> service = new UserService<>();

    public String show(long id) {
        User user = service.getUser(id, "web");
        return user.getName();
    }
}
