'use strict';
const params = require('../parameters.js');

module.exports = (sequelize, DataTypes) => {
  const Experiment = sequelize.define('Experiment', {
    website: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    file: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    email: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    ccas: DataTypes.ARRAY(DataTypes.ENUM(params.ccas)),
    experimentType: {
      type: DataTypes.ENUM('Fairness', 'Classification'),
      allowNull: false,
    },
    predictedLabel: DataTypes.STRING,
    status: {
      type: DataTypes.ENUM('Queued', 'In Progress', 'Completed', 'Failed'),
      allowNull: false,
      defaultValue: 'Queued'
    },
    directory: DataTypes.STRING,
  }, {});

  Experiment.associate = (models) => {
    Experiment.hasMany(models.Flow, {
      foreignKey: 'experimentId',
      as: 'flows',
    });
  };

  return Experiment;
};