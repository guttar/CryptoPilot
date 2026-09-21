<template>
  <div>
    <h2>控制台</h2>
    <p>欢迎使用 RAG 系统。</p>
    <el-row :gutter="20">
      <el-col :span="8">
        <el-card shadow="hover" @click="$router.push('/knowledge-bases')">
          管理知识库
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" @click="$router.push('/chat')">
          开始对话
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" @click="$router.push('/evaluation')">
          运行评估
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>
